import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import fixture from '../../src/admin/numerical-applicability.fixture.json' with { type: 'json' }
import numerical from '../../src/admin/numerical.fixture.json' with { type: 'json' }
import existing from '../../src/admin/fixtures.generated.json' with { type: 'json' }
import type { NumericalApplicabilityRequest } from '../../src/admin/generated'
import { apiOrigin } from '../ports'
import { expectRenderedSource } from './pdf'

// Blank authored PDF and backend-validated declared words. No real human review.
const root = `/v1/admin/numerical/gates/${fixture.packet.gate.id}`
type Mode = 'eligible' | 'blocked' | 'wrong-gate' | 'wrong-membership' | 'retry' | 'wrong-receipt' | 'source-mismatch' | 'stale' | 'restore' | 'history-unavailable' | 'rerun-retry' | 'rerun-membership'
async function setup(page: Page, mode: Mode = 'eligible') {
  const state = { writes: [] as NumericalApplicabilityRequest[], saved: mode === 'restore' || mode.startsWith('rerun-'), reruns: 0 }
  const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'ETag,Content-Length' }
  const envelope = (data: unknown) => ({ data, meta: numerical.private_meta })
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname
    if (request.method() === 'OPTIONS') { await route.fulfill({ status: 204, headers: { ...headers, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' } }); return }
    if (path === '/v1/auth/token') { await route.fulfill({ headers, json: { access_token: 'authored-admin-token', token_type: 'bearer' } }); return }
    if (path === '/v1/auth/admin/me') { await route.fulfill({ headers, json: existing.identity }); return }
    expect(request.headers().authorization).toBe('Bearer authored-admin-token')
    if (path.includes('/queues/')) { await route.fulfill({ headers, json: existing.queues.filings }); return }
    if (path === root) { await route.fulfill({ headers, json: envelope(fixture.packet) }); return }
    if (path === root + '/applicability/requirements') {
      const value = structuredClone(fixture.requirements)
      if (mode === 'blocked') Object.assign(value, { eligible: false, blockers: ['METRIC requires resolution before applicability review.', 'ISSUER requires resolution before applicability review.'] })
      if (mode === 'wrong-gate') value.gate_run_id = '00000000-0000-4000-8000-000000000001'
      if (mode === 'wrong-membership') value.assertions[0]!.evidence_ids.reverse()
      await route.fulfill({ headers, json: envelope(value) }); return
    }
    if (path === root + '/applicability') {
      if (request.method() === 'POST') {
        const body = request.postDataJSON() as NumericalApplicabilityRequest; state.writes.push(body)
        expect(body).toEqual(fixture.review.request)
        if (mode === 'stale') { await route.fulfill({ status: 409, headers, json: {} }); return }
        state.saved = true
        if (mode === 'retry' && state.writes.length === 1) { await route.fulfill({ status: 503, headers, json: {} }); return }
        if (mode === 'wrong-receipt' && state.writes.length === 1) { await route.fulfill({ headers, json: envelope({ ...fixture.review, request: { ...fixture.review.request, note: 'Substituted note.' } }) }); return }
      } else if (mode === 'history-unavailable') { await route.fulfill({ status: 503, headers, json: {} }); return }
      await route.fulfill({ status: state.saved ? 200 : 404, headers, json: envelope(fixture.review) }); return
    }
    if (path === root + '/applicability/gate') {
      state.reruns += 1
      expect(request.postDataJSON()).toEqual({})
      if (mode === 'rerun-retry' && state.reruns === 1) { await route.fulfill({ status: 503, headers, json: {} }); return }
      const result = structuredClone(fixture.resolved)
      if (mode === 'rerun-membership' && state.reruns === 1) result.applicability_review_id = '00000000-0000-4000-8000-000000000001'
      await route.fulfill({ headers, json: envelope(result) }); return
    }
    if (path.startsWith('/v1/evidence/')) {
      const word = fixture.packet.binding.phrases.flatMap((phrase) => phrase.words).find((item) => path.endsWith(item.evidence.id))
      expect(word).toBeDefined()
      const evidence = structuredClone(numerical.evidence)
      Object.assign(evidence.data, { record: word!.evidence, source_sha256: fixture.packet.binding.source_sha256, processing_configuration_sha256: fixture.packet.binding.processing_configuration_sha256 })
      Object.assign(evidence.meta.versions, { filing_version_id: fixture.packet.binding.filing_version_id, parse_version_id: fixture.packet.binding.parse_version_id })
      if (mode === 'source-mismatch') evidence.data.processing_configuration_sha256 = 'e'.repeat(64)
      await route.fulfill({ headers, json: evidence }); return
    }
    if (path.endsWith('/source.pdf')) {
      const bytes = Buffer.from(fixture.pdf_base64, 'base64')
      await route.fulfill({ headers: { ...headers, 'Content-Type': 'application/pdf', 'Content-Length': String(bytes.length), ETag: `"${fixture.packet.binding.source_sha256}"` }, body: bytes }); return
    }
    await route.fulfill({ status: 404, headers, json: {} })
  })
  await page.goto('/')
  await page.getByRole('link', { name: 'Administrator workspace', exact: true }).click()
  await page.getByLabel('Administrator username', { exact: true }).fill('authored-admin')
  await page.getByLabel('Administrator password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: 'Sign in as administrator', exact: true }).click()
  await page.getByRole('button', { name: 'Numerical filings', exact: true }).click()
  await page.getByLabel('Saved numerical gate ID', { exact: true }).fill(fixture.packet.gate.id)
  await page.getByRole('button', { name: 'Load numerical review', exact: true }).click()
  await page.getByRole('button', { name: 'Check applicability requirements and history', exact: true }).click()
  return state
}

async function inspectAll(page: Page): Promise<void> {
  // Eight sequential verified PDF renders took 37s on the local Windows host.
  // Only these multi-source review scenarios need the larger bounded budget.
  test.setTimeout(90_000)
  const panel = page.getByRole('region', { name: 'Numerical source applicability review', exact: true })
  const buttons = panel.getByRole('button', { name: /^Inspect applicability word 1 in /u })
  await expect(buttons.first()).toBeVisible()
  const total = await buttons.count(); expect(total).toBeGreaterThan(3)
  for (let index = 0; index < total; index += 1) {
    await buttons.nth(index).click()
    await expectRenderedSource(page)
  }
  await expect(panel.getByRole('checkbox')).toBeEnabled()
}
async function submit(page: Page): Promise<void> {
  await page.getByLabel('Applicability review note', { exact: true }).fill(fixture.review.request.note)
  await page.getByRole('region', { name: 'Numerical source applicability review', exact: true }).getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Record applicability review', exact: true }).click()
}

test('all exact assertions require source inspection and an explicit review while context remains unresolved', async ({ page }) => {
  const state = await setup(page)
  const panel = page.getByRole('region', { name: 'Numerical source applicability review', exact: true })
  await expect(panel.getByRole('checkbox')).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Record applicability review', exact: true })).toBeDisabled()
  await expect(panel.getByText(/Selected source pages: 1, 2/u)).toBeVisible()
  await expect(panel.getByText(/QUALIFIED_DEFAULT/u)).toHaveCount(2)
  await inspectAll(page); await submit(page)
  await expect(panel.getByText('Recorded applicability decision: APPLIES', { exact: true })).toBeVisible()
  await expect(panel.getByText(/stored gate remains REVIEW_REQUIRED/u)).toBeVisible()
  await expect(page.getByLabel('Numerical context decision', { exact: true }).locator('option[value="CONFIRM_CONTEXT"]')).toBeDisabled()
  expect(state.writes).toHaveLength(1)
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('missing canonical approval prerequisites block review and cannot be checked away', async ({ page }) => {
  const state = await setup(page, 'blocked')
  await expect(page.getByLabel('Applicability blockers')).toContainText('METRIC requires resolution')
  await expect(page.getByLabel('Applicability blockers')).toContainText('ISSUER requires resolution')
  await expect(page.getByLabel('Applicability review note', { exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Record applicability review', exact: true })).toBeDisabled()
  expect(state.writes).toHaveLength(0)
})

for (const mode of ['wrong-gate', 'wrong-membership', 'history-unavailable'] as const) test(`unverified ${mode} cannot display a writable applicability form`, async ({ page }) => {
  const state = await setup(page, mode)
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Applicability review note', { exact: true })).toHaveCount(0)
  expect(state.writes).toHaveLength(0)
})

for (const mode of ['retry', 'wrong-receipt'] as const) test(`${mode} keeps all review operations frozen until the exact submitted request is verified`, async ({ page }) => {
  const state = await setup(page, mode); await inspectAll(page)
  await page.getByLabel('Context review note', { exact: true }).fill('An unrelated context decision must not interrupt the pending applicability write.')
  await submit(page)
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toBeDisabled()
  await expect(page.getByLabel('Applicability review note', { exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Record context decision', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Filing jobs', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Check applicability requirements and history', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Retry the same applicability review', exact: true }).click()
  await expect(page.getByText('Recorded applicability decision: APPLIES', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toBeEnabled()
  expect(state.writes).toHaveLength(2); expect(state.writes[0]).toEqual(state.writes[1])
})

test('a source identity failure does not count as completed inspection', async ({ page }) => {
  const state = await setup(page, 'source-mismatch')
  await page.getByRole('button', { name: 'Inspect applicability word 1 in value 1', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('original word, PDF or parse configuration differs')
  await expect(page.getByRole('region', { name: 'Exact source page', exact: true })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Numerical source applicability review', exact: true }).getByRole('checkbox')).toBeDisabled()
  expect(state.writes).toHaveLength(0)
})

test('a stale source rejection clears eligibility and requires an explicit refresh', async ({ page }) => {
  const state = await setup(page, 'stale'); await inspectAll(page); await submit(page)
  await expect(page.getByRole('alert')).toContainText('conflicts with stored history')
  await expect(page.getByLabel('Applicability review note', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Check applicability requirements and history', exact: true })).toBeEnabled()
  expect(state.writes).toHaveLength(1)
})

test('a retained applicability review restores without a new approval request', async ({ page }) => {
  const state = await setup(page, 'restore')
  await expect(page.getByText('Recorded applicability decision: APPLIES', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Applicability review note', { exact: true })).toHaveCount(0)
  expect(state.writes).toHaveLength(0)
})

for (const mode of ['restore', 'rerun-retry', 'rerun-membership'] as const) test(`${mode} rerun preserves ancestry and opens a new gate for separate context confirmation`, async ({ page }) => {
  const state = await setup(page, mode)
  await page.getByRole('button', { name: 'Rerun numerical gates with recorded applicability', exact: true }).click()
  if (mode !== 'restore') {
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Filing jobs', exact: true })).toBeDisabled()
    await expect(page.getByLabel('Numerical context decision', { exact: true }).locator('option[value="CONFIRM_CONTEXT"]')).toBeDisabled()
    await page.getByRole('button', { name: 'Retry the same numerical gate rerun', exact: true }).click()
  }
  await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toHaveValue(fixture.resolved.packet.gate.id)
  await expect(page.getByText('Stored gate: READY_FOR_REVIEW', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Numerical context decision', { exact: true }).locator('option[value="CONFIRM_CONTEXT"]')).toBeEnabled()
  await expect(page.getByText('Recorded context decision: CONFIRM_CONTEXT', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add accepted numerical candidate to draft', exact: true })).toHaveCount(0)
  expect(state.reruns).toBe(mode === 'restore' ? 1 : 2)
  expect(state.writes).toHaveLength(0)
})
