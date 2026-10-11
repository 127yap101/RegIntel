import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Card } from './Card'

describe('Card', () => {
  it('gives each region its own heading and keeps its content associated', () => {
    render(<><Card title="Backend connection"><p>Unavailable</p></Card><Card title="Project scope"><p>Foundation only</p></Card></>)
    const backend = screen.getByRole('region', { name: 'Backend connection' })
    const scope = screen.getByRole('region', { name: 'Project scope' })
    expect(within(backend).getByText('Unavailable')).toBeVisible()
    expect(within(scope).getByText('Foundation only')).toBeVisible()
    expect(backend.getAttribute('aria-labelledby')).not.toBe(scope.getAttribute('aria-labelledby'))
  })
})
