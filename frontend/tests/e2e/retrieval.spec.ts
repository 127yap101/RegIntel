import { apiOrigin, webOrigin } from '../ports'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { expectRenderedSource } from './pdf'
import reads from '../../src/published/fixtures.generated.json' with { type: 'json' }
import fixtures from '../../src/retrieval/fixtures.generated.json' with { type: 'json' }
import type { RetrievalRequest } from '../../src/retrieval/generated'

async function setup(page: Page, mode = 'normal'): Promise<void> {
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const path = new URL(route.request().url()).pathname
    const headers = { 'Access-Control-Allow-Origin': webOrigin, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,HEAD,OPTIONS', 'Access-Control-Expose-Headers': 'ETag,Content-Length,X-Corpus-Version-ID' }
    if (route.request().method() === 'OPTIONS') { await route.fulfill({ status: 204, headers }); return }
    if (path.endsWith('/source.pdf')) { const pdf = Buffer.from(reads.pdf_base64, 'base64'); await route.fulfill({ body: pdf, contentType: 'application/pdf', headers: { ...headers, 'Content-Length': String(pdf.length), ETag: `"${reads.evidence.data.evidence.source_sha256}"`, 'X-Corpus-Version-ID': reads.info.data.corpus_version_id } }); return }
    if (path === '/v1/answers') {
      if (mode === 'graph-failure') { await route.fulfill({ status: 503, headers, json: { error: 'Authored outage' } }); return }
      const request = JSON.parse(route.request().postData() ?? '{}') as RetrievalRequest
      expect(request.corpus_version_id).toBe(reads.info.data.corpus_version_id)
      expect(route.request().headers().authorization).toBe('Bearer authored-browser-token')
      const result = structuredClone(fixtures.answer)
      Object.assign(result.data.retrieval.trace, { arm: request.arm, filters: request.filters })
      if (mode === 'mixed') result.data.retrieval.view.corpus_version_id = '00000000-0000-4000-8000-000000000001'
      if (mode === 'numeric') { result.data.state = 'NUMERIC_CONTEXT_REQUIRED'; result.data.claims = []; result.data.retrieval.hits = []; result.data.explanation = 'Exact numeric context is required; no value was inferred.'; result.data.retrieval.trace.context_tokens = 0 }
      await route.fulfill({ status: 200, headers, json: result }); return
    }
    const value: unknown = path === '/v1/auth/token' ? { access_token: 'authored-browser-token', token_type: 'bearer' } : path === '/v1/published-corpus' ? reads.info : path === '/v1/companies' ? reads.companies : path.endsWith('/facts') ? reads.facts : path.endsWith('/graph') ? reads.graph : path.includes('/evidence/') ? reads.evidence : null
    await route.fulfill({ status: value ? 200 : 404, headers, json: value })
  })
  await page.goto('/')
  await page.getByLabel('Username', { exact: true }).fill('authored-learner')
  await page.getByLabel('Password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: 'Sign in to inspect filings' }).click()
  await page.getByRole('button', { name: 'Alpha Energy Limited', exact: true }).click()
}

async function ask(page: Page, question = 'What initial public offering is proposed?'): Promise<void> {
  await page.getByLabel('Question', { exact: true }).fill(question)
  await page.getByRole('button', { name: 'Find cited evidence', exact: true }).click()
}

test('question returns a conditional source excerpt and opens its real PDF.js page', async ({ page }) => {
  await setup(page); await ask(page)
  const panel = page.getByRole('region', { name: 'Questions about published filings', exact: true })
  await expect(panel.getByText('Verbatim source excerpt', { exact: true })).toBeVisible()
  await expect(panel.locator('blockquote')).toContainText('subject to approvals')
  await panel.getByRole('button', { name: 'Source 1 · page 1', exact: true }).click()
  await expectRenderedSource(page)
  await expect(page.getByTestId('evidence-region')).toHaveCount(1)
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.getByLabel('Question', { exact: true }).fill('An updated question after reading the source')
  await expect(page.getByLabel('Question', { exact: true })).toHaveValue('An updated question after reading the source')
})

test('mixed answer corpus fails without showing unverified claims', async ({ page }) => {
  await setup(page, 'mixed'); await ask(page)
  await expect(page.getByRole('alert')).toContainText('answer or its exact source could not be verified')
  await expect(page.getByText('Verbatim source excerpt', { exact: true })).toHaveCount(0)
})

test('numeric question shows explicit missing context without inventing values', async ({ page }) => {
  await setup(page, 'numeric'); await ask(page, 'How much revenue?')
  await expect(page.getByText('No supported answer is available for this request.', { exact: true })).toBeVisible()
  await expect(page.getByText('Exact numeric context is required; no value was inferred.')).toBeVisible()
})

test('graph retrieval outage has an explicit error without changing methods', async ({ page }) => {
  await setup(page, 'graph-failure'); await ask(page)
  await expect(page.getByRole('alert')).toContainText('could not be loaded')
  await expect(page.getByLabel('Search method')).toHaveValue('B3')
})

test('sign out aborts an in-flight answer and clears question state', async ({ page }) => {
  await setup(page)
  let release: () => void = () => {}
  const pending = new Promise<void>((resolve) => { release = resolve })
  await page.route('**/v1/answers', async (route) => { await pending; await route.fulfill({ json: fixtures.answer }).catch(() => {}) })
  await ask(page)
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  release()
  await expect(page.getByRole('button', { name: 'Sign in to inspect filings' })).toBeVisible()
  await expect(page.getByLabel('Question', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Verbatim source excerpt', { exact: true })).toHaveCount(0)
})
