import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import fixture from '../../src/admin/numerical-queue.fixture.json' with { type: 'json' }
import existing from '../../src/admin/fixtures.generated.json' with { type: 'json' }
import { apiOrigin } from '../ports'

const root = '/v1/admin/numerical/gates'
const selected = fixture.pages.unreviewed.data.items[0]!
const label = selected.company_name_raw
const other = '00000000-0000-4000-8000-000000000001'

// Retained actual owned HTTP pages; routing/echo failures below are controlled cases.
async function setup(page: Page) {
  const state: { unavailable: boolean; revoked: boolean; mixed: boolean; slow: boolean; finished: boolean; release?: () => void; writes: number; queries: string[] } = { unavailable: false, revoked: false, mixed: false, slow: false, finished: false, writes: 0, queries: [] }
  const headers = { 'Access-Control-Allow-Origin': '*' }
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname
    if (request.method() === 'OPTIONS') { await route.fulfill({ status: 204, headers: { ...headers, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' } }); return }
    if (path === '/v1/auth/token') { await route.fulfill({ headers, json: { access_token: 'authored-admin-token', token_type: 'bearer' } }); return }
    if (path === '/v1/auth/admin/me') { await route.fulfill({ headers, json: existing.identity }); return }
    expect(request.headers().authorization).toBe('Bearer authored-admin-token')
    if (state.revoked) { await route.fulfill({ status: 403, headers, json: {} }); return }
    if (request.method() !== 'GET') { state.writes += 1; await route.fulfill({ status: 409, headers, json: {} }); return }
    if (path.includes('/queues/')) { await route.fulfill({ headers, json: existing.queues.filings }); return }
    if (path === root) {
      if (state.unavailable) { await route.fulfill({ status: 503, headers, json: {} }); return }
      if (state.slow) await new Promise<void>((resolve) => { state.release = resolve })
      const review = url.searchParams.get('review'); const query = url.searchParams.get('query') ?? ''; const offset = Number(url.searchParams.get('offset') ?? '0')
      state.queries.push(query)
      const value = structuredClone(review === 'ALL' ? offset === 20 ? fixture.pages.all_next : fixture.pages.all : review === 'CONFIRM_CONTEXT' ? fixture.pages.confirmed : review === 'REJECT' ? fixture.pages.rejected : fixture.pages.unreviewed)
      if (!label.toLowerCase().includes(query.toLowerCase())) { value.data.items = []; value.data.has_more = false }
      Object.assign(value.data, { query, state_filter: url.searchParams.get('state') ?? 'ALL' })
      if (state.mixed && value.data.items[0]) value.data.items[0].filing_version_id = other
      try { await route.fulfill({ headers, json: value }) } catch { /* Logout intentionally cancels the pending read. */ }
      state.finished = true; return
    }
    const packet = Object.entries(fixture.packets).find(([id]) => path === root + '/' + id)?.[1]
    if (packet) { await route.fulfill({ headers, json: packet }); return }
    await route.fulfill({ status: 404, headers, json: {} })
  })
  await page.goto('/')
  await page.getByRole('link', { name: 'Administrator workspace', exact: true }).click()
  await page.getByLabel('Administrator username', { exact: true }).fill('authored-admin')
  await page.getByLabel('Administrator password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: 'Sign in as administrator', exact: true }).click()
  await page.getByRole('button', { name: 'Numerical filings', exact: true }).click()
  return state
}

test('numerical queue opens an actual stored check without a pasted ID and clears its notes on new filters', async ({ page }) => {
  const state = await setup(page)
  const area = page.getByRole('region', { name: 'Stored numerical checks', exact: true })
  await page.getByRole('button', { name: 'Find numerical checks', exact: true }).click()
  await expect(area.getByText(label + ' · RHP', { exact: true })).toBeVisible()
  await expect(area.locator('script')).toHaveCount(0)
  await page.getByRole('button', { name: `Open numerical check ${selected.gate.id}`, exact: true }).click()
  await expect(page.getByText('Stored gate: READY_FOR_REVIEW', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toHaveValue(selected.gate.id)
  await page.getByLabel('Numerical context decision', { exact: true }).selectOption('CONFIRM_CONTEXT')
  await page.getByLabel('Context review note', { exact: true }).fill('Unsubmitted authored note')
  await page.getByLabel('Uploaded company name contains', { exact: true }).fill('<script>')
  await expect(page.getByRole('region', { name: 'Numerical context review', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toHaveValue('')
  await page.getByRole('button', { name: 'Find numerical checks', exact: true }).click()
  await page.getByRole('button', { name: `Open numerical check ${selected.gate.id}`, exact: true }).click()
  await expect(page.getByLabel('Context review note', { exact: true })).toHaveValue('')
  await expect(page.getByLabel('Numerical context decision', { exact: true })).toHaveValue('REJECT')
  expect(state.queries).toContain('<script>'); expect(state.writes).toBe(0)
})

test('numerical queue shows actual twenty-row and continuation pages within a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 })
  await setup(page)
  const area = page.getByRole('region', { name: 'Stored numerical checks', exact: true })
  await page.getByLabel('Recorded numerical context review', { exact: true }).selectOption('ALL')
  await page.getByRole('button', { name: 'Find numerical checks', exact: true }).click()
  await expect(area.getByRole('button', { name: /^Open numerical check / })).toHaveCount(20)
  await page.getByRole('button', { name: 'More numerical checks', exact: true }).click()
  await expect(area.getByRole('button', { name: /^Open numerical check / })).toHaveCount(3)
  await expect(page.getByRole('button', { name: 'More numerical checks', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Previous numerical checks', exact: true }).click()
  await expect(area.getByRole('button', { name: /^Open numerical check / })).toHaveCount(20)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('numerical queue rejects a selected row whose complete source packet belongs to another filing', async ({ page }) => {
  const state = await setup(page); state.mixed = true
  await page.getByRole('button', { name: 'Find numerical checks', exact: true }).click()
  await page.getByRole('button', { name: `Open numerical check ${selected.gate.id}`, exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('differs from its loaded source')
  await expect(page.getByRole('region', { name: 'Numerical context review', exact: true })).toHaveCount(0)
  expect(state.writes).toBe(0)
})

test('numerical queue separates unavailable storage from empty results and clears on revocation', async ({ page }) => {
  const state = await setup(page)
  const area = page.getByRole('region', { name: 'Stored numerical checks', exact: true })
  await page.getByRole('button', { name: 'Find numerical checks', exact: true }).click()
  await expect(area.getByText(label + ' · RHP', { exact: true })).toBeVisible()
  state.unavailable = true
  await page.getByRole('button', { name: 'Refresh numerical checks', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('could not be completed')
  await expect(area.getByText(/No stored numerical checks match/)).toHaveCount(0)
  await expect(area.getByRole('button', { name: /^Open numerical check / })).toHaveCount(0)
  state.unavailable = false
  await page.getByRole('button', { name: 'Find numerical checks', exact: true }).click()
  await expect(area.getByRole('button', { name: /^Open numerical check / })).toHaveCount(1)
  state.revoked = true
  await page.getByRole('button', { name: 'Refresh numerical checks', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign in as administrator', exact: true })).toBeVisible()
  await expect(area).toHaveCount(0)
})

test('a recorded context review cannot disappear when a numerical queue row is opened', async ({ page }) => {
  const state = await setup(page)
  await page.getByLabel('Recorded numerical context review', { exact: true }).selectOption('CONFIRM_CONTEXT')
  await page.getByRole('button', { name: 'Find numerical checks', exact: true }).click()
  // Controlled downgrade: a confirmed row followed by its earlier unreviewed packet.
  await page.getByRole('button', { name: `Open numerical check ${selected.gate.id}`, exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('differs from its queued audit')
  await expect(page.getByRole('region', { name: 'Numerical context review', exact: true })).toHaveCount(0)
  expect(state.writes).toBe(0)
})

test('logout cancels a pending numerical queue read and prevents private rows from returning', async ({ page }) => {
  const state = await setup(page); state.slow = true
  await page.getByRole('button', { name: 'Find numerical checks', exact: true }).click()
  await expect.poll(() => typeof state.release).toBe('function')
  await page.getByRole('button', { name: 'Sign out of administrator workspace', exact: true }).click()
  state.release?.()
  await expect.poll(() => state.finished).toBe(true)
  await expect(page.getByRole('region', { name: 'Stored numerical checks', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => sessionStorage.length + localStorage.length)).toBe(0)
})
