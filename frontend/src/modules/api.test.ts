import { afterEach, describe, expect, it, vi } from 'vitest'
import { decode, ModuleApi, ModuleError, orderInput } from './api'
import { confirmOrder, pendingOrder, retainOrder } from './pending'
import { definition, envelope, glossary, ids, opening, rejection, request, user } from './fixtures.test-support'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

describe('M3/M4 wire and source versions', () => {
  it('reads independently versioned approved glossary and exact educational decimals', () => {
    const result = decode('glossary', envelope(glossary, { glossary_version_id: ids.glossary }))
    expect(result.definitions[0]?.definition.calculation?.result).toBe('0.30')
    expect(result.definitions[0]?.definition.draft.definition).toContain('<script>')
    expect(decode('definition', envelope(definition)).id).toBe(ids.definition)
  })
  it('rejects an unapproved publication and mismatched module version', () => {
    const wrong = structuredClone(glossary)
    wrong.definitions[0]!.review.decision = 'REJECT'
    expect(() => decode('glossary', envelope(wrong, { glossary_version_id: ids.glossary }))).toThrow(ModuleError)
    expect(() => decode('portfolio', envelope(opening, { portfolio_version_id: ids.order }))).toThrow(ModuleError)
    expect(() => decode('glossary', envelope(glossary))).toThrow(ModuleError)
  })
  it('rejects numeric coercion, client price injection and a different quote/corpus', () => {
    expect(() => orderInput({ ...request, quantity: '3' })).toThrow(ModuleError)
    expect(() => orderInput({ ...request, price: '0.01' })).toThrow(ModuleError)
    expect(() => orderInput({ ...request, quantity: 1.5 })).toThrow(ModuleError)
    expect(() => decode('order', envelope(rejection(), { portfolio_version_id: ids.order, corpus_version_id: ids.account }))).toThrow(ModuleError)
    expect(() => decode('order', envelope(rejection(), { portfolio_version_id: ids.order, corpus_version_id: request.corpus_version_id, quote_version_id: ids.glossary }))).toThrow(ModuleError)
  })
  it('retains only an exact per-user request for reload/retry and clears after confirmation', () => {
    retainOrder(ids.user, orderInput(request))
    expect(pendingOrder(ids.user)).toEqual(request)
    expect(pendingOrder(ids.account)).toBeNull()
    expect(sessionStorage.getItem(`regintel.pending-virtual-order.${ids.user}`)).toBe(JSON.stringify(request))
    confirmOrder(ids.user)
    expect(pendingOrder(ids.user)).toBeNull()
  })
  it('refuses malformed stored requests and stops before sending when storage is unavailable', () => {
    sessionStorage.setItem(`regintel.pending-virtual-order.${ids.user}`, JSON.stringify({ ...request, price: '1.00' }))
    expect(pendingOrder(ids.user)).toBeNull()
    vi.stubGlobal('sessionStorage', { setItem: () => { throw new Error('Authored quota failure') } })
    expect(() => retainOrder(ids.user, orderInput(request))).toThrow('No new order was sent')
  })
  it('checks the recorded payload and sends bearer only in authenticated headers', async () => {
    const changed = rejection({ ...request, quantity: 4 })
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'authored-module-token', token_type: 'bearer' })))
      .mockResolvedValueOnce(new Response(JSON.stringify(envelope(user))))
      .mockResolvedValueOnce(new Response(JSON.stringify(envelope(changed, { portfolio_version_id: ids.order, corpus_version_id: request.corpus_version_id }))))
    vi.stubGlobal('fetch', fetcher)
    const signal = new AbortController().signal
    const session = await ModuleApi.login('authored', 'authored-password', signal)
    await expect(session.order(orderInput(request), signal)).rejects.toThrow('differs from the submitted request')
    expect(fetcher.mock.calls[2]?.[1]).toMatchObject({ credentials: 'omit', redirect: 'error', cache: 'no-store', headers: { Authorization: 'Bearer authored-module-token' } })
    expect(sessionStorage.length).toBe(0)
  })
})
