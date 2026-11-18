import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./published/Explorer', () => ({ Explorer: ({ selectedCorpus, onSelectCorpus }: { selectedCorpus: string | null; onSelectCorpus: (value: string | null) => void }) => <section><h2>Published filing explorer</h2><label>Research selection<input defaultValue="" /></label><p>Explorer corpus: {selectedCorpus ?? 'none'}</p><button onClick={() => onSelectCorpus('selected-corpus')}>Select reviewed corpus</button></section> }))
vi.mock('./admin/Workspace', () => ({ AdminWorkspace: () => <section>Current administrator workspace</section> }))
vi.mock('./modules/Workspace', () => ({ ModuleWorkspace: ({ mode, selectedCorpus, onSelectCorpus }: { mode: string; selectedCorpus: string | null; onSelectCorpus: (value: string | null) => void }) => <section><h2>{mode === 'learning' ? 'Financial learning' : 'Virtual portfolio'}</h2><p>Module corpus: {selectedCorpus ?? 'none'}</p><button onClick={() => onSelectCorpus(null)}>Clear selected corpus</button></section> }))

function route(path: string) { window.history.replaceState({}, '', path) }
const restoreDialog: (() => void)[] = []
function mockDialog(name: 'showModal' | 'close', method: (this: HTMLDialogElement) => void) {
  const previous = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name)
  Object.defineProperty(HTMLDialogElement.prototype, name, { configurable: true, value: method })
  restoreDialog.push(() => {
    if (previous) Object.defineProperty(HTMLDialogElement.prototype, name, previous)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name)
  })
}

describe('integrated workspace navigation', () => {
  beforeEach(() => {
    route('/')
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ status: 'ok', service: 'RegIntel Finance', environment: 'test' }), { headers: { 'Content-Type': 'application/json' } })))
  })
  afterEach(() => { route('/'); restoreDialog.splice(0).forEach((restore) => restore()) })

  it('preserves the M1 research view across M1/M2 paths and carries its corpus to other modules', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('Backend available')
    await user.type(screen.getByLabelText('Research selection'), 'Retain selected company')
    await user.click(screen.getByRole('button', { name: 'Select reviewed corpus' }))
    await user.click(screen.getByRole('link', { name: 'Analysis & comparison' }))
    expect(window.location.pathname).toBe('/app/comparison')
    expect(screen.getByLabelText('Research selection')).toHaveValue('Retain selected company')
    expect(screen.getByText('Explorer corpus: selected-corpus')).toBeVisible()
    await user.click(screen.getByRole('link', { name: 'Financial learning' }))
    expect(screen.getByText('Module corpus: selected-corpus')).toBeVisible()
    await user.click(screen.getByRole('link', { name: 'Virtual portfolio' }))
    expect(screen.getByRole('heading', { name: 'Virtual portfolio' })).toBeVisible()
    expect(screen.getByText('Module corpus: selected-corpus')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Clear selected corpus' }))
    await user.click(screen.getByRole('link', { name: 'Explore published filings' }))
    expect(screen.getByText('Explorer corpus: none')).toBeVisible()
  })

  it('opens a direct module URL and responds to browser history changes', async () => {
    route('/app/portfolio')
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Virtual portfolio' })).toBeVisible()
    route('/app/learning')
    fireEvent.popState(window)
    expect(await screen.findByRole('heading', { name: 'Financial learning' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Financial learning' })).toHaveAttribute('aria-current', 'page')
  })

  it('rejects unknown routes without silently displaying another workspace', () => {
    route('/app/missing-page')
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Published filing explorer' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Return to overview' })).toHaveAttribute('href', '/')
  })

  it('opens the mobile navigation as a modal and closes it on cancel with focus restored', async () => {
    // Pinned jsdom has no native dialog methods; the browser suite checks them.
    mockDialog('showModal', function (this: HTMLDialogElement) { this.setAttribute('open', '') })
    mockDialog('close', function (this: HTMLDialogElement) { this.removeAttribute('open') })
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('Backend available')
    const opener = screen.getByRole('button', { name: 'Open navigation' })
    const focus = HTMLElement.prototype.focus.bind(opener)
    vi.spyOn(opener, 'focus').mockImplementation(() => {
      // jsdom does not enforce native modal inertness; reproduce that boundary.
      if (!document.querySelector('dialog[open]')) focus()
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'Workspace navigation' })
    expect(within(dialog).getByRole('button', { name: 'Close navigation' })).toHaveFocus()
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
    expect(opener).toHaveAttribute('aria-expanded', 'false')
  })
})
