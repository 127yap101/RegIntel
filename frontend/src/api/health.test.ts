import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_API_BASE_URL, fetchBackendHealth, getApiBaseUrl, HEALTH_TIMEOUT_MS } from './health'

const healthy = { status: 'ok', service: 'RegIntel Finance', environment: 'development' } as const

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('backend health client', () => {
  beforeEach(() => vi.stubEnv('VITE_API_BASE_URL', DEFAULT_API_BASE_URL))
  afterEach(() => vi.useRealTimers())

  it('normalizes a configured base and rejects credentials or unsupported protocols', () => {
    expect(getApiBaseUrl('  http://127.0.0.1:8000/api/  ')).toBe('http://127.0.0.1:8000/api')
    expect(getApiBaseUrl('')).toBe(DEFAULT_API_BASE_URL)
    expect(() => getApiBaseUrl('file:///tmp/api')).toThrow('HTTP address')
    expect(() => getApiBaseUrl('http://user:password@localhost:8000')).toThrow('without credentials')
  })

  it('requests liveness at the configured endpoint and validates its response', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(healthy))
    vi.stubGlobal('fetch', fetchMock)
    await expect(fetchBackendHealth(undefined, 'http://127.0.0.1:8000/api/')).resolves.toEqual(healthy)
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/health/live', expect.objectContaining({ method: 'GET', cache: 'no-store' }))
  })

  it('rejects an HTTP failure even if the body looks healthy', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(healthy, 503)))
    await expect(fetchBackendHealth()).rejects.toMatchObject({ code: 'http' })
  })

  it.each([
    { status: 'ok', service: 'Another service', environment: 'development' },
    { status: 'ok', service: 'RegIntel Finance', environment: 'unknown' },
    { status: 'error', service: 'RegIntel Finance', environment: 'test' },
    null,
  ])('rejects an invalid health contract: %j', async (payload) => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(payload)))
    await expect(fetchBackendHealth()).rejects.toMatchObject({ code: 'contract' })
  })

  it('rejects malformed JSON instead of declaring the backend healthy', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('not json')))
    await expect(fetchBackendHealth()).rejects.toMatchObject({ code: 'contract' })
  })

  it('reports a network failure explicitly', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(fetchBackendHealth()).rejects.toMatchObject({ code: 'network' })
  })

  it('aborts a stalled request after the bounded timeout and clears its timer', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((_input, init) => new Promise<Response>((_resolve, reject) => {
      if (!init?.signal) throw new Error('Expected an abort signal')
      init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    })))
    const result = expect(fetchBackendHealth()).rejects.toMatchObject({ code: 'timeout' })
    await vi.advanceTimersByTimeAsync(HEALTH_TIMEOUT_MS)
    await result
    expect(vi.getTimerCount()).toBe(0)
  })

  it('preserves caller cancellation as cancellation rather than an outage', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn<typeof fetch>((_input, init) => new Promise<Response>((_resolve, reject) => {
      if (!init?.signal) throw new Error('Expected an abort signal')
      init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    })))
    const result = expect(fetchBackendHealth(controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    controller.abort()
    await result
  })
})
