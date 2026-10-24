import { ModuleError, orderInput } from './api'
import type { OrderRequest } from './generated'

// Retain only the exact unconfirmed request, scoped to the current account.
// Authentication tokens and server balances are never stored in the browser.
const key = (userId: string): string => `regintel.pending-virtual-order.${userId}`

export function pendingOrder(userId: string): OrderRequest | null {
  try {
    const body = sessionStorage.getItem(key(userId))
    return body === null ? null : orderInput(JSON.parse(body) as unknown)
  } catch { return null }
}

export function retainOrder(userId: string, request: OrderRequest): void {
  try { sessionStorage.setItem(key(userId), JSON.stringify(orderInput(request))) }
  catch { throw new ModuleError(0, 'The browser could not retain this request for a safe retry. No new order was sent.') }
}

export function confirmOrder(userId: string): void {
  try { sessionStorage.removeItem(key(userId)) } catch { /* A replay remains safe if storage is unavailable. */ }
}
