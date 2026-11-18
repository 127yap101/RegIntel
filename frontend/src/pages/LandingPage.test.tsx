import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LandingPage } from './LandingPage'

describe('landing workspace navigation', () => {
  it('keeps all four modules reachable through the current workspace owner', () => {
    const choose = vi.fn()
    render(<LandingPage connection={<p>Connection check belongs to the application.</p>} onChooseWorkspace={choose} />)
    for (const [label, workspace, path] of [
      ['Start with published filings', 'published', '/app/companies'],
      ['Open review workspace', 'admin', '/admin'],
      ['Explore filing evidence', 'published', '/app/companies'],
      ['Open company comparisons', 'published', '/app/comparison'],
      ['Open financial learning', 'learning', '/app/learning'],
      ['Open virtual portfolio', 'portfolio', '/app/portfolio'],
    ] as const) {
      const link = screen.getByRole('link', { name: label })
      expect(link).toHaveAttribute('href', path)
      fireEvent.click(link)
      expect(choose).toHaveBeenLastCalledWith(workspace, path)
    }
    expect(choose).toHaveBeenCalledTimes(6)
    expect(screen.getByText('Connection check belongs to the application.')).toBeVisible()
  })

  it.each<MouseEventInit>([{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }])('preserves native navigation for modified clicks: %j', (options) => {
    const choose = vi.fn()
    render(<LandingPage connection={null} onChooseWorkspace={choose} />)
    const nativeDefault: boolean[] = []
    const observe = (event: MouseEvent) => {
      nativeDefault.push(event.defaultPrevented)
      // Suppress jsdom navigation only after observing React's handler.
      event.preventDefault()
    }
    document.addEventListener('click', observe)
    try {
      fireEvent.click(screen.getByRole('link', { name: 'Open company comparisons' }), options)
    } finally {
      document.removeEventListener('click', observe)
    }
    expect(nativeDefault).toEqual([false])
    expect(choose).not.toHaveBeenCalled()
  })
})
