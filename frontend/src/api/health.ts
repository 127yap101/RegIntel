export const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000'
export const HEALTH_TIMEOUT_MS = 5_000

export type BackendEnvironment = 'development' | 'test' | 'production'

export interface BackendHealth {
  status: 'ok'
  service: 'RegIntel Finance'
  environment: BackendEnvironment
}

type HealthErrorCode = 'configuration' | 'http' | 'contract' | 'timeout' | 'network'

export class HealthCheckError extends Error {
  constructor(
    public readonly code: HealthErrorCode,
    message: string,
  ) {
    super(message)
    this.name = 'HealthCheckError'
  }
}

export function getApiBaseUrl(configured = import.meta.env.VITE_API_BASE_URL): string {
  const value = configured?.trim() || DEFAULT_API_BASE_URL
  let url: URL
  try {
    url = new URL(value)
  } catch {
    throw new HealthCheckError('configuration', 'The backend address is not configured correctly.')
  }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new HealthCheckError('configuration', 'The backend address must be an HTTP address without credentials.')
  }
  return url.toString().replace(/\/+$/, '')
}

function isBackendHealth(value: unknown): value is BackendHealth {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const record = value as Record<string, unknown>
  return (
    record.status === 'ok' &&
    record.service === 'RegIntel Finance' &&
    (record.environment === 'development' || record.environment === 'test' || record.environment === 'production')
  )
}

export async function fetchBackendHealth(signal?: AbortSignal, apiBaseUrl?: string): Promise<BackendHealth> {
  const endpoint = `${getApiBaseUrl(apiBaseUrl)}/health/live`
  const controller = new AbortController()
  const cancel = (): void => controller.abort()
  signal?.addEventListener('abort', cancel, { once: true })
  if (signal?.aborted) controller.abort()
  let timedOut = false
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, HEALTH_TIMEOUT_MS)

  try {
    const response = await fetch(endpoint, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: controller.signal,
    })
    if (!response.ok) {
      throw new HealthCheckError('http', 'The backend is not responding successfully. Please retry.')
    }
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      throw new HealthCheckError('contract', 'The backend returned an unexpected health response.')
    }
    if (!isBackendHealth(payload)) {
      throw new HealthCheckError('contract', 'The backend returned an unexpected health response.')
    }
    return payload
  } catch (error: unknown) {
    if (signal?.aborted) throw new DOMException('The health request was cancelled.', 'AbortError')
    if (timedOut) throw new HealthCheckError('timeout', 'The backend health check timed out. Please retry.')
    if (error instanceof HealthCheckError) throw error
    throw new HealthCheckError('network', 'The backend could not be reached. Check the local API and retry.')
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
  }
}
