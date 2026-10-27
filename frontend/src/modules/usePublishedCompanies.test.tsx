import { act, renderHook, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { decode } from '../published/api'
import type { CompanyPage, PublishedApi } from '../published/api'
import { published } from './fixtures.test-support'
import { usePublishedCompanies } from './usePublishedCompanies'

const page = decode('companies', published.companies)
const view = decode('info', published.info)
const other = '00000000-0000-4000-8000-000000000081'
const client = () => ({ current: vi.fn<PublishedApi['current']>().mockResolvedValue(view), companies: vi.fn<PublishedApi['companies']>().mockResolvedValue(page) })
function pageAt(corpus: string): CompanyPage {
  const value = structuredClone(published.companies)
  value.data.view.corpus_version_id = corpus; value.meta.versions.corpus_version_id = corpus
  return decode('companies', value)
}

describe('shared published company selection', () => {
  it('keeps the supplied corpus without consulting a newer head', async () => {
    const api = client(); const selected = vi.fn()
    api.current.mockResolvedValue({ ...view, corpus_version_id: pageAt(other).view.corpus_version_id })
    const { result } = renderHook(() => usePublishedCompanies(api, view.corpus_version_id, selected))
    await waitFor(() => expect(result.current.companies).toEqual(page))
    expect(api.current).not.toHaveBeenCalled()
    expect(api.companies).toHaveBeenCalledWith({ corpus: view.corpus_version_id, historical: false, asOf: '' }, '', 0, expect.any(AbortSignal))
    expect(selected).toHaveBeenCalledExactlyOnceWith(view.corpus_version_id)
  })

  it('verifies the initial head once and avoids a duplicate read when the parent retains it', async () => {
    const api = client(); const selected = vi.fn()
    const { result, rerender } = renderHook(({ corpus }) => usePublishedCompanies(api, corpus, selected), { initialProps: { corpus: null as string | null } })
    await waitFor(() => expect(result.current.companies).toEqual(page))
    rerender({ corpus: view.corpus_version_id })
    expect(api.current).toHaveBeenCalledTimes(1)
    expect(api.companies).toHaveBeenCalledTimes(1)
    expect(selected).toHaveBeenCalledExactlyOnceWith(view.corpus_version_id)
  })

  it('keeps a failed selected corpus unavailable instead of falling back to the head', async () => {
    const api = client(); const selected = vi.fn()
    api.companies.mockRejectedValue(new Error('Unavailable selected corpus'))
    const { result } = renderHook(() => usePublishedCompanies(api, view.corpus_version_id, selected))
    await waitFor(() => expect(result.current.error).toContain('selected filing corpus could not be verified'))
    expect(result.current.companies).toBeNull()
    expect(api.current).not.toHaveBeenCalled()
    expect(selected).not.toHaveBeenCalled()
  })

  it('does not start a replaced development effect or resolve the head twice', async () => {
    const api = client(); const selected = vi.fn()
    const { result } = renderHook(() => usePublishedCompanies(api, null, selected), { wrapper: StrictMode })
    await waitFor(() => expect(result.current.companies).toEqual(page))
    expect(api.current).toHaveBeenCalledTimes(1)
    expect(api.companies).toHaveBeenCalledTimes(1)
    expect(selected).toHaveBeenCalledExactlyOnceWith(view.corpus_version_id)
  })

  it('cannot promote a company page from another corpus', async () => {
    const api = client(); const selected = vi.fn()
    const { result } = renderHook(() => usePublishedCompanies(api, other, selected))
    await waitFor(() => expect(result.current.error).not.toBe(''))
    expect(result.current.companies).toBeNull()
    expect(api.current).not.toHaveBeenCalled()
    expect(selected).not.toHaveBeenCalled()
  })

  it('ignores a delayed response after the selection changed', async () => {
    const api = client(); const selected = vi.fn()
    let complete: ((value: CompanyPage) => void) | undefined
    api.companies.mockImplementationOnce(() => new Promise<CompanyPage>((resolve) => { complete = resolve }))
    const next = pageAt(other)
    api.companies.mockResolvedValue(next)
    const { result, rerender } = renderHook(({ corpus }) => usePublishedCompanies(api, corpus, selected), { initialProps: { corpus: String(view.corpus_version_id) } })
    await waitFor(() => expect(api.companies).toHaveBeenCalledTimes(1))
    rerender({ corpus: other })
    await waitFor(() => expect(result.current.companies).toEqual(next))
    expect(complete).toBeTypeOf('function')
    await act(async () => { complete?.(page); await Promise.resolve() })
    expect(result.current.companies).toEqual(next)
    expect(selected).toHaveBeenCalledExactlyOnceWith(other)
    expect(api.companies.mock.calls[0]?.[3].aborted).toBe(true)
  })

  it('can reselect a verified older corpus after another selection failed', async () => {
    const api = client(); const selected = vi.fn()
    const { result, rerender } = renderHook(({ corpus }) => usePublishedCompanies(api, corpus, selected), { initialProps: { corpus: String(view.corpus_version_id) } })
    await waitFor(() => expect(result.current.companies).toEqual(page))
    api.companies.mockRejectedValueOnce(new Error('Unavailable'))
    rerender({ corpus: other })
    await waitFor(() => expect(result.current.error).not.toBe(''))
    rerender({ corpus: view.corpus_version_id })
    await waitFor(() => expect(result.current.companies).toEqual(page))
    expect(result.current.error).toBe('')
    expect(api.current).not.toHaveBeenCalled()
  })
})
