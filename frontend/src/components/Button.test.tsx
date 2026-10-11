import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { FormEvent } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Button } from './Button'

describe('Button', () => {
  it('supports keyboard activation and an accessible name', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Check backend</Button>)
    await user.tab()
    expect(screen.getByRole('button', { name: 'Check backend' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('does not accidentally submit a surrounding form', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn((event: FormEvent) => event.preventDefault())
    render(<form onSubmit={onSubmit}><Button>Check backend</Button></form>)
    await user.click(screen.getByRole('button', { name: 'Check backend' }))
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('blocks interaction when disabled', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button disabled onClick={onClick}>Checking</Button>)
    await user.click(screen.getByRole('button', { name: 'Checking' }))
    expect(onClick).not.toHaveBeenCalled()
  })
})
