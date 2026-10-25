import { afterEach, describe, expect, it, vi } from 'vitest'
import { decode, ModuleApi, ModuleError, orderInput } from './api'
import { confirmOrder, pendingOrder, retainOrder } from './pending'
import { analytics, definition, envelope, glossary, ids, opening, rejection, request, reviewed, user } from './fixtures.test-support'
import starters from '../../../data/learning-starter-drafts.json'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

describe('M3/M4 wire and source versions', () => {
  it('keeps starter content unreviewed, source-linked and independent of M1 metric IDs', () => {
    expect(decode('starter_pack', envelope(starters)).drafts).toHaveLength(7)
    expect(() => decode('starter_pack', envelope({ ...starters, status: 'APPROVED' }))).toThrow(ModuleError)
    expect(() => decode('starter_pack', envelope({ ...starters, reviewed_by: 'invented reviewer' }))).toThrow(ModuleError)
    const changed = { ...starters, drafts: starters.drafts.map((item, index) => index === 0 ? { ...item, draft: { ...item.draft, metric_ids: [ids.account] } } : item) }
    expect(() => decode('starter_pack', envelope(changed))).toThrow('reviewed metric mapping')
  })
  it('pins dependent history requests to the selected account version and checks ownership', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'authored-module-token', token_type: 'bearer' })))
      .mockResolvedValueOnce(new Response(JSON.stringify(envelope(user))))
      .mockResolvedValueOnce(new Response(JSON.stringify(envelope(opening, { portfolio_version_id: ids.account }))))
      .mockResolvedValueOnce(new Response(JSON.stringify(envelope({ account_id: ids.account, portfolio_version_id: ids.account, entries: [], total: 0, offset: 0 }, { portfolio_version_id: ids.account }))))
    vi.stubGlobal('fetch', fetcher)
    const signal = new AbortController().signal
    const session = await ModuleApi.login('authored', 'authored-password', signal)
    const selected = (await session.portfolioSnapshot(signal)).account
    expect(selected).toEqual(opening)
    expect(fetcher.mock.calls[3]?.[0]).toContain(`portfolio_version_id=${ids.account}`)
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify(envelope({ account_id: ids.user, portfolio_version_id: ids.account, entries: [], total: 0, offset: 0 }, { portfolio_version_id: ids.account }))))
    await expect(session.ledgerSnapshot(selected, signal)).rejects.toThrow('selected virtual account version')
    const recorded = decode('portfolio', envelope({ ...opening, portfolio_version_id: ids.order, committed_orders: 1 }, { portfolio_version_id: ids.order }))
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify(envelope({ account_id: ids.account, portfolio_version_id: ids.order, entries: [{ ...rejection().entry, sequence: 2 }], total: 1, offset: 0 }, { portfolio_version_id: ids.order }))))
    await expect(session.ledgerSnapshot(recorded, signal)).rejects.toThrow('selected virtual account version')
  })
  it('keeps draft decisions private and tied to the selected immutable definition', () => {
    const item = { definition, state: 'APPROVED', review: reviewed }
    const queue = { items: [item], state: 'ALL', query: '', offset: 0, limit: 20, total: 1 }
    expect(decode('drafts', envelope(queue)).items[0]?.review?.review_id).toBe(ids.review)
    expect(() => decode('drafts', envelope({ ...queue, state: 'PENDING_REVIEW' }))).toThrow('recorded reviews')
    expect(() => decode('drafts', envelope(queue, { glossary_version_id: ids.glossary }))).toThrow(ModuleError)
    expect(() => decode('drafts', envelope({ ...queue, items: [{ ...item, review: null }] }))).toThrow(ModuleError)
  })
  it('requires complete analytics membership and explicit unavailable valuation', () => {
    const data = analytics(true)
    expect(decode('analytics', envelope(data, { portfolio_version_id: ids.order })).summary?.cash).toBe('100000.00')
    expect(() => decode('analytics', envelope({ ...data, input_entry_ids: [] }, { portfolio_version_id: ids.order }))).toThrow('incomplete or mixed')
    expect(() => decode('analytics', envelope(data, { portfolio_version_id: ids.account }))).toThrow(ModuleError)
    expect(() => decode('analytics', envelope(data, { portfolio_version_id: ids.order, corpus_version_id: request.corpus_version_id }))).toThrow('source-version membership')
    expect(() => decode('analytics', envelope({ ...data, state: 'LEDGER_BUDGET_EXCEEDED' }, { portfolio_version_id: ids.order }))).toThrow('partial totals')
  })
  it('rejects an open-position result rather than presenting its cash flow as profit', () => {
    const data = analytics(true)
    const company = { company_id: request.company_id, bought_quantity: 3, sold_quantity: 1, quantity: 2, buy_spend: '30.00', sale_proceeds: '12.00', net_cash_flow: '-18.00', position_state: 'OPEN', closed_position_result: '-18.00' }
    expect(() => decode('analytics', envelope({ ...data, companies: [company] }, { portfolio_version_id: ids.order }))).toThrow('closed-position result')
  })
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
