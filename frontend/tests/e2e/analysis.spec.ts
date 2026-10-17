import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { apiOrigin, webOrigin } from '../ports'
import fixtures from '../../src/analysis/fixtures.generated.json' with { type: 'json' }

type Mode = { state?: 'CONFLICT' | 'MISSING' | 'INCOMPATIBLE'; revoked?: boolean; mixed?: boolean; wrongPdf?: boolean }

async function authoredApi(page: Page, mode: Mode = {}): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const url = new URL(route.request().url())
    const headers = { 'Access-Control-Allow-Origin': webOrigin, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,HEAD,OPTIONS', 'Access-Control-Expose-Headers': 'ETag,Content-Length,X-Corpus-Version-ID' }
    if (route.request().method() === 'OPTIONS') { await route.fulfill({ status: 204, headers }); return }
    if (mode.revoked && url.pathname !== '/v1/auth/token') { await route.fulfill({ status: 401, headers }); return }
    if (url.pathname.endsWith('/source.pdf')) {
      const pdf = mode.wrongPdf ? Buffer.from('%PDF-wrong') : Buffer.from(fixtures.pdf_base64, 'base64')
      const evidence = Object.values(fixtures.evidence)[0]!
      await route.fulfill({ status: 200, body: pdf, contentType: 'application/pdf', headers: { ...headers, 'Content-Length': String(pdf.length), ETag: `"${evidence.data.evidence.source_sha256}"`, 'X-Corpus-Version-ID': fixtures.request.corpus_version_id } }); return
    }
    let data: unknown
    if (url.pathname === '/v1/auth/token') data = { access_token: 'authored-m2-browser-token', token_type: 'bearer' }
    else if (url.pathname === '/v1/published-corpus') data = fixtures.info
    else if (url.pathname === '/v1/companies') data = fixtures.companies
    else if (url.pathname === '/v1/quotes') data = fixtures.quotes
    else if (url.pathname === '/v1/compare') {
      const result = structuredClone(fixtures.comparison)
      expect(route.request().postDataJSON()).toEqual(fixtures.request)
      if (mode.mixed) result.meta.versions.corpus_version_id = '00000000-0000-4000-8000-000000000001'
      if (mode.state) {
        const cell = result.data.rows[0]!.cells[1]!
        Object.assign(cell, { state: mode.state, normalized: null, explanation: `Authored ${mode.state.toLowerCase()} scenario.` })
        if (mode.state === 'MISSING') cell.inputs = []
        Object.assign(result.data.rows[0]!.differences[0]!, { state: 'UNAVAILABLE', input_observation_ids: [], unit: null, currency: null, difference: null, percentage_state: 'UNAVAILABLE', percentage_difference: null })
      }
      data = result
    } else {
      const company = url.pathname.split('/')[3]
      if (url.pathname.endsWith('/facts')) data = fixtures.facts[company as keyof typeof fixtures.facts]
      else if (url.pathname.endsWith('/graph')) data = fixtures.graphs[company as keyof typeof fixtures.graphs]
      else if (url.pathname.includes('/evidence/')) data = fixtures.evidence[url.pathname.split('/').at(-1) as keyof typeof fixtures.evidence]
    }
    await route.fulfill(data ? { status: 200, headers, json: data } : { status: 404, headers })
  })
}

async function prepareComparison(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Username', { exact: true }).fill('authored.learner')
  await page.getByLabel('Password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: 'Sign in to inspect filings' }).click()
  await page.getByRole('button', { name: 'Alpha Energy Limited', exact: true }).click()
  await page.getByRole('checkbox', { name: 'Alpha Energy Limited', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Beta Solar Limited', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Revenue (authored fixture)', exact: true }).check()
  await page.getByLabel('Period start', { exact: true }).fill('2025-04-01')
  await page.getByLabel('Period end', { exact: true }).fill('2026-03-31')
}

test('M2 exact comparison retains raw inputs and opens the corresponding second PDF page', async ({ page }) => {
  await authoredApi(page); await prepareComparison(page)
  await page.getByRole('button', { name: 'Compare published values' }).click()
  await expect(page.getByRole('table')).toContainText('125000000.00 INR')
  await expect(page.getByText('Difference: 25000000.00 INR. Percentage difference: 20.000000%.', { exact: true })).toBeVisible()
  await expect(page.getByText(/Quotes unavailable:/)).toBeVisible()
  await page.getByText('Input disclosures: Beta Solar Limited (1)', { exact: true }).click()
  const details = page.locator('details').filter({ hasText: 'Input disclosures: Beta Solar Limited (1)' })
  await expect(details).toContainText('150 million INR')
  await details.getByRole('button', { name: 'Inspect source 1', exact: true }).click()
  await expect(page.getByText('Source verified · page rendered')).toBeVisible()
  await expect(page.locator('canvas[aria-label="Original filing page 2"]')).toBeVisible()
  await expect(page.getByTestId('evidence-region')).toHaveCount(1)
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})

for (const state of ['CONFLICT', 'MISSING', 'INCOMPATIBLE'] as const) {
  test(`M2 ${state.toLowerCase()} input leaves explicit unavailable calculations`, async ({ page }) => {
    await authoredApi(page, { state }); await prepareComparison(page)
    await page.getByRole('button', { name: 'Compare published values' }).click()
    await expect(page.getByRole('table')).toContainText(state)
    await expect(page.getByText(/Difference: Unavailable/)).toBeVisible()
    await expect(page.getByText('Difference: 25000000.00 INR. Percentage difference: 20.000000%.', { exact: true })).toHaveCount(0)
  })
}

test('M2 rejects a response from another corpus and clears results after session expiry', async ({ page }) => {
  const mode: Mode = { mixed: true }
  await authoredApi(page, mode); await prepareComparison(page)
  await page.getByRole('button', { name: 'Compare published values' }).click()
  await expect(page.getByRole('alert')).toContainText('comparison or its exact inputs could not be verified')
  await expect(page.getByRole('table')).toHaveCount(0)
  mode.mixed = false
  await page.getByRole('button', { name: 'Compare published values' }).click()
  await expect(page.getByRole('table')).toBeVisible()
  mode.revoked = true
  await page.getByRole('button', { name: 'Compare published values' }).click()
  await expect(page.getByRole('button', { name: 'Sign in to inspect filings' })).toBeVisible()
  await expect(page.getByRole('table')).toHaveCount(0)
})

test('M2 fits a narrow viewport and clears comparison inputs on logout', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 })
  await authoredApi(page); await prepareComparison(page)
  await page.getByRole('button', { name: 'Compare published values' }).click()
  await expect(page.getByRole('table')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('table')).toHaveCount(0)
  await expect(page.getByRole('checkbox', { name: 'Beta Solar Limited' })).toHaveCount(0)
})
