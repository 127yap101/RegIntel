import { apiOrigin, webOrigin } from '../ports'
import { expect, test } from '@playwright/test'
import type { Route } from '@playwright/test'

const healthUrl = `${apiOrigin}/health/live`

async function fulfillHealth(route: Route): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    headers: { 'access-control-allow-origin': webOrigin },
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
  await expect(page.getByText('Reviewed learning', { exact: true })).toBeVisible()
  await expect(page.getByText('Virtual ledger', { exact: true })).toBeVisible()
})

test('welcome screen is accessible on a narrow viewport and labels all modules honestly', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.route(healthUrl, fulfillHealth)
  await page.goto('/')
  await expect(page).toHaveTitle('RegIntel Finance · Published filings')
  await expect(page.getByRole('status')).toContainText('Backend available')
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeVisible()
  await expect(page.getByText('Reviewed learning', { exact: true })).toBeVisible()
  await expect(page.getByText('Virtual ledger', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Corporate Intelligence' })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()
  await page.getByRole('button', { name: 'Open navigation' }).click()
  const navigation = page.getByRole('dialog', { name: 'Workspace navigation' })
  await expect(navigation).toBeVisible()
  await expect(navigation.getByRole('link', { name: 'Explore published filings' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(navigation).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeFocused()
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await navigation.getByRole('button', { name: 'Close navigation' }).click()
  await expect(navigation).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('workspace paths support direct entry, browser back and explicit missing pages', async ({ page }) => {
  await page.route(healthUrl, fulfillHealth)
  await page.goto('/app/learning')
  await expect(page.getByRole('heading', { name: 'Financial learning', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Virtual portfolio', exact: true }).click()
  await expect(page).toHaveURL(/\/app\/portfolio$/u)
  await expect(page.getByRole('heading', { name: 'Virtual portfolio', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Financial learning', exact: true })).toBeVisible()
  await page.goto('/app/unknown')
  await expect(page.getByRole('heading', { name: 'Page not found', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Published filing explorer' })).toHaveCount(0)
  await page.getByRole('link', { name: 'Return to overview' }).click()
  await expect(page.getByRole('heading', { name: 'Four connected modules' })).toBeVisible()
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
  await expect(page.getByText('Reviewed learning', { exact: true })).toBeVisible()
  await expect(page.getByText('Virtual ledger', { exact: true })).toBeVisible()
})
