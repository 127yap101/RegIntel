import { expect, test } from '@playwright/test'
import type { Route } from '@playwright/test'

const healthUrl = 'http://127.0.0.1:8000/health/live'

async function fulfillHealth(route: Route): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    headers: { 'access-control-allow-origin': 'http://127.0.0.1:5173' },
    body: JSON.stringify({ status: 'ok', service: 'RegIntel Finance', environment: 'test' }),
  })
}

test('browser connects to the real local FastAPI liveness endpoint', async ({ page }) => {
  const healthResponse = page.waitForResponse(healthUrl)
  await page.goto('/')
  const response = await healthResponse
  expect(response.status()).toBe(200)
  const payload: unknown = await response.json()
  expect(payload).toEqual({ status: 'ok', service: 'RegIntel Finance', environment: 'test' })
  await expect(page.getByRole('status')).toContainText('Backend available')
  await expect(page.getByRole('status')).toContainText('Connected to the test API')
  await expect(page.getByText('Not implemented', { exact: true })).toHaveCount(3)
})

test('welcome screen is accessible on a narrow viewport and labels all modules honestly', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.route(healthUrl, fulfillHealth)
  await page.goto('/')
  await expect(page).toHaveTitle('RegIntel Finance · Published filings')
  await expect(page.getByRole('status')).toContainText('Backend available')
  await expect(page.getByRole('link', { name: 'Explore published filings' })).toBeVisible()
  await expect(page.getByText('Not implemented', { exact: true })).toHaveCount(3)
  await expect(page.getByRole('heading', { name: 'Corporate Intelligence' })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('unavailable backend can recover through a keyboard-activated retry', async ({ page }) => {
  let available = false
  await page.route(healthUrl, async (route) => {
    if (available) await fulfillHealth(route)
    else await route.abort('connectionrefused')
  })
  await page.goto('/')
  await expect(page.getByRole('status')).toContainText('Backend unavailable')
  available = true
  await page.getByRole('button', { name: 'Check backend' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('status')).toContainText('Backend available')
  await expect(page.getByText('Not implemented', { exact: true })).toHaveCount(3)
})
