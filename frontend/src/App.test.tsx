import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { DEFAULT_API_BASE_URL } from './api/health'
vi.mock('./published/SourceViewer', () => ({ SourceViewer: () => null }))

function healthResponse(environment = 'development'): Response {
  return new Response(JSON.stringify({ status: 'ok', service: 'RegIntel Finance', environment }), { headers: { 'Content-Type': 'application/json' } })
}

describe('foundation welcome screen', () => {
  beforeEach(() => vi.stubEnv('VITE_API_BASE_URL', DEFAULT_API_BASE_URL))

  it('separates process liveness from authenticated published data', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(healthResponse()))
    render(<App />)
    expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled()
    await screen.findByText('Backend available')
    expect(screen.getByRole('status')).toHaveTextContent('confirms liveness only')
    expect(screen.getByRole('heading', { name: 'Published filing explorer' })).toBeVisible()
    expect(screen.getAllByText('Not implemented')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Sign in to inspect filings' })).toBeVisible()
  })

  it('reports unavailability and lets the user retry successfully', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(healthResponse('test'))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await screen.findByText('Backend unavailable')
    await user.click(screen.getByRole('button', { name: 'Check backend' }))
    await screen.findByText('Backend available')
    expect(screen.getByRole('status')).toHaveTextContent('Connected to the test API')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.getAllByText('Not implemented')).toHaveLength(2)
  })

  it('does not present a malformed successful HTTP response as available', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(healthResponse('unsupported')))
    render(<App />)
    await screen.findByText('Backend unavailable')
    expect(screen.queryByText('Backend available')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('unexpected health response')
  })
})
