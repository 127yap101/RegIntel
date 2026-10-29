import { apiOrigin, webOrigin } from '../ports'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { expectRenderedSource } from './pdf'
import fixtures from '../../src/published/fixtures.generated.json' with { type: 'json' }

async function authoredApi(page: Page, mode: { revoked?: boolean; wrongPdf?: boolean; rawText?: string } = {}): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const url = new URL(route.request().url())
    const headers = { 'Access-Control-Allow-Origin': webOrigin, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,HEAD,OPTIONS', 'Access-Control-Expose-Headers': 'ETag,Content-Length,X-Corpus-Version-ID' }
    if (route.request().method() === 'OPTIONS') { await route.fulfill({ status: 204, headers }); return }
    if (mode.revoked && url.pathname !== '/v1/auth/token') { await route.fulfill({ status: 401, headers, json: { error: 'authored revocation' } }); return }
    if (url.pathname.endsWith('/source.pdf')) {
      const pdf = mode.wrongPdf ? Buffer.from('%PDF-wrong') : Buffer.from(fixtures.pdf_base64, 'base64')
      await route.fulfill({ status: 200, body: pdf, contentType: 'application/pdf', headers: { ...headers, 'Content-Length': String(pdf.length), ETag: `"${fixtures.evidence.data.evidence.source_sha256}"`, 'X-Corpus-Version-ID': fixtures.info.data.corpus_version_id } }); return
    }
    let data: unknown
    if (url.pathname === '/v1/auth/token') data = { access_token: 'authored-browser-token', token_type: 'bearer' }
    else if (url.pathname === '/v1/published-corpus') data = fixtures.info
    else if (url.pathname === '/v1/companies') {
      data = url.searchParams.has('as_of_date') ? { ...fixtures.companies, data: { ...fixtures.companies.data, companies: [], total: 0, view: { ...fixtures.companies.data.view, state: 'TEMPORAL_SUPPORT_UNAVAILABLE', as_of_date: url.searchParams.get('as_of_date') } } } : fixtures.companies
    } else if (url.pathname.endsWith('/facts')) {
      const result = structuredClone(fixtures.facts)
      if (mode.rawText && result.data.facts[0]) result.data.facts[0].observation.raw_text = mode.rawText
      data = result
    }
    else if (url.pathname.endsWith('/graph')) data = fixtures.graph
    else if (url.pathname.includes('/evidence/')) data = fixtures.evidence
    else { await route.fulfill({ status: 404, headers }); return }
    await route.fulfill({ status: 200, json: data, headers })
  })
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Username', { exact: true }).fill('authored.learner')
  await page.getByLabel('Password', { exact: true }).fill('authored-test-password')
  await page.getByRole('button', { name: 'Sign in to inspect filings' }).click()
  await page.getByRole('button', { name: 'Alpha Energy Limited', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Offering proposal' })).toBeVisible()
}

test('authored published slice renders a real PDF.js canvas and the retained region', async ({ page }) => {
  await authoredApi(page); await signIn(page)
  await expect(page.getByText('No corporate relations are published in this view.')).toBeVisible()
  await page.getByRole('button', { name: 'Inspect source 1' }).click()
  await expectRenderedSource(page)
  await expect(page.getByTestId('evidence-region')).toHaveCount(1)
  // Canvas has an accessible label but no implicit role; inspect its pixels directly.
  const drawn = await page.locator('canvas[aria-label="Original filing page 1"]').evaluate((element) => {
    const canvas = element as HTMLCanvasElement
    const data = canvas.getContext('2d')?.getImageData(50, 80, 500, 40).data
    return data ? Array.from(data).some((value, index) => index % 4 !== 3 && value < 100) : false
  })
  expect(drawn).toBe(true)
  await expect(page.getByText('subject to approvals.', { exact: false }).last()).toBeVisible()
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})

test('hash mismatch stops source rendering and leaves an explicit error', async ({ page }) => {
  await authoredApi(page, { wrongPdf: true }); await signIn(page)
  await page.getByRole('button', { name: 'Inspect source 1' }).click()
  await expect(page.getByRole('alert')).toContainText('hash does not match')
  await expect(page.locator('canvas[aria-label="Original filing page 1"]')).toHaveCount(0)
})

test('unknown as-of support clears the prior selection without inventing a result', async ({ page }) => {
  await authoredApi(page); await signIn(page)
  await page.getByLabel('As-of date (optional)').fill('2026-01-01')
  await page.getByRole('button', { name: 'Apply view' }).click()
  await expect(page.getByText(/date view is unavailable/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Offering proposal' })).toHaveCount(0)
})

test('revocation and logout clear the in-memory published state', async ({ page }) => {
  const mode = { revoked: false }
  await authoredApi(page, mode); await signIn(page)
  mode.revoked = true
  await page.getByRole('button', { name: 'Apply view' }).click()
  await expect(page.getByRole('alert')).toContainText('session has expired')
  await expect(page.getByRole('button', { name: 'Sign in to inspect filings' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Offering proposal' })).toHaveCount(0)
})

test('filing text remains inert text instead of source HTML', async ({ page }) => {
  const rawText = '<img src="invalid" onerror="document.body.dataset.injected=1"> Authored source text.'
  await authoredApi(page, { rawText }); await signIn(page)
  await expect(page.getByText(rawText, { exact: true })).toBeVisible()
  await expect(page.locator('img')).toHaveCount(0)
  expect(await page.locator('body').getAttribute('data-injected')).toBeNull()
})

test('logout aborts a pending read and cannot repopulate private results', async ({ page }) => {
  await authoredApi(page); await signIn(page)
  let release: () => void = () => {}
  const pending = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/v1/companies?**', async (route) => {
    await pending
    await route.fulfill({ status: 200, json: fixtures.companies, headers: { 'Access-Control-Allow-Origin': webOrigin } }).catch(() => {})
  })
  await page.getByRole('button', { name: 'Apply view' }).click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  release()
  await expect(page.getByRole('button', { name: 'Sign in to inspect filings' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Offering proposal' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Alpha Energy Limited', exact: true })).toHaveCount(0)
})
