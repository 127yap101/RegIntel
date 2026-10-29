import { apiOrigin, webOrigin } from '../ports'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { expectRenderedSource } from './pdf'
import fixtures from '../../src/admin/fixtures.generated.json' with { type: 'json' }
import type { ProcessingRequest, PublicationRequest, ReviewDecision } from '../../src/admin/generated'

interface Proof { reviews: ReviewDecision[]; builds: PublicationRequest[]; published: number; revoked: boolean; processing: ProcessingRequest[]; uploads: Record<string, string>[] }
async function setup(page: Page, mode = 'normal'): Promise<Proof> {
  const state: Proof = { reviews: [], builds: [], published: 0, revoked: false, processing: [], uploads: [] }
  let stored: ReviewDecision | null = null
  let approved = structuredClone(fixtures.manifest)
  const headers = { 'Access-Control-Allow-Origin': webOrigin, 'Content-Type': 'application/json', 'Access-Control-Expose-Headers': 'ETag,Content-Length' }
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname
    if (request.method() === 'OPTIONS') { await route.fulfill({ status: 204, headers: { ...headers, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' } }); return }
    if (path === '/v1/auth/token') { await route.fulfill({ headers, json: { access_token: 'authored-admin-token', token_type: 'bearer' } }); return }
    if (path === '/v1/auth/admin/me') { await route.fulfill({ status: mode === 'learner' ? 403 : 200, headers, json: fixtures.identity }); return }
    expect(request.headers().authorization).toBe('Bearer authored-admin-token')
    if (state.revoked) { await route.fulfill({ status: 403, headers, json: { detail: 'Authoritative role changed' } }); return }
    if (path.includes('/queues/')) {
      const kind = path.split('/').at(-1) as keyof typeof fixtures.queues
      const result = structuredClone(fixtures.queues[kind])
      if (mode === 'empty') result.data.items = []
      await route.fulfill({ headers, json: result }); return
    }
    if (path === '/v1/admin/workspace/metrics') { await route.fulfill({ headers, json: fixtures.metrics }); return }
    if (path === '/v1/filings') { state.uploads.push(Object.fromEntries(url.searchParams)); expect(request.headers()['content-type']).toBe('application/pdf'); await route.fulfill({ headers, json: fixtures.filing_job }); return }
    if (path.startsWith('/v1/filing-jobs/')) { await route.fulfill({ headers, json: fixtures.filing_job }); return }
    if (path === '/v1/admin/processing/jobs') {
      const body = request.postDataJSON() as ProcessingRequest; state.processing.push(body)
      const result = structuredClone(fixtures.processing_queued); Object.assign(result.data, { request: body })
      await route.fulfill({ headers, json: result }); return
    }
    if (path.startsWith('/v1/admin/processing/jobs/') && path.endsWith('/dispatch')) { await route.fulfill({ headers, json: { data: { dispatched: true }, meta: fixtures.identity.meta } }); return }
    if (path.startsWith('/v1/admin/processing/jobs/')) {
      const result = structuredClone(fixtures.processing_completed)
      if (state.processing[0]) Object.assign(result.data, { request: state.processing[0] })
      await route.fulfill({ headers, json: result }); return
    }
    if (path.includes('/workspace/reviews/')) {
      if (mode === 'slow') await new Promise((resolve) => setTimeout(resolve, 500))
      const result = structuredClone(fixtures.review_page)
      Object.assign(result.data, { state_filter: url.searchParams.get('state') ?? 'ALL' })
      const item = result.data.items[0]!
      if (mode === 'quarantine') { item.result.state = 'QUARANTINED'; item.result.reviewer_eligible = false; const check = item.result.checks.find((entry) => entry.code === 'CURRENCY')!; check.state = 'FAIL'; check.message = 'Authored contradictory currency/unit evidence.' }
      if (stored) Object.assign(item, { review: stored })
      try { await route.fulfill({ headers, json: result }) } catch { /* The logout test deliberately aborts this read. */ }
      return
    }
    if (path === '/v1/admin/validation/reviews') {
      const body = request.postDataJSON() as ReviewDecision
      state.reviews.push(body); stored = body
      expect(body.supports).toEqual(fixtures.review_page.data.items[0]!.draft.supports)
      if (mode === 'retry' && state.reviews.length === 1) { await route.fulfill({ status: 503, headers, json: {} }); return }
      await route.fulfill({ headers, json: { data: { review_id: body.id, already_exists: state.reviews.length > 1 }, meta: fixtures.identity.meta } }); return
    }
    if (path === '/v1/admin/publication/builds' && request.method() === 'POST') {
      const body = request.postDataJSON() as PublicationRequest; state.builds.push(body)
      if (mode === 'amendment') { await route.fulfill({ status: 422, headers, json: {} }); return }
      const result = structuredClone(fixtures.manifest)
      Object.assign(result.data, { parent_corpus_version_id: body.parent_corpus_version_id })
      if (stored) { result.data.observations[0]!.review_id = stored.id; result.data.new_acceptances[0]!.observation.review_id = stored.id; Object.assign(result.data.new_acceptances[0]!.original_review, { decision: stored }) }
      approved = result; await route.fulfill({ headers, json: result }); return
    }
    if (path.endsWith('/publish')) { state.published += 1; await route.fulfill({ headers, json: approved }); return }
    if (path.startsWith('/v1/evidence/')) { await route.fulfill({ headers, json: fixtures.evidence }); return }
    if (path.endsWith('/source.pdf')) {
      const bytes = Buffer.from(fixtures.pdf_base64, 'base64'); if (mode === 'bad-source') bytes[bytes.length - 1] = bytes[bytes.length - 1]! ^ 1
      await route.fulfill({ headers: { ...headers, 'Content-Type': 'application/pdf', 'Content-Length': String(bytes.length), ETag: `"${fixtures.evidence.data.source_sha256}"` }, body: bytes }); return
    }
    await route.fulfill({ status: 404, headers, json: {} })
  })
  await page.goto('/')
  await page.getByRole('link', { name: 'Administrator workspace', exact: true }).click()
  await page.getByLabel('Administrator username', { exact: true }).fill('authored-admin')
  await page.getByLabel('Administrator password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: 'Sign in as administrator', exact: true }).click()
  return state
}
async function review(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Validation and quarantine', exact: true }).click()
  await page.getByRole('button').filter({ hasText: fixtures.review_page.data.run_id }).click()
}
async function note(page: Page): Promise<void> { await page.getByLabel('Decision note', { exact: true }).fill('Reviewed the complete authored source including all conditions.') }

test('administrator can start with no published corpus and no jobs', async ({ page }) => {
  await setup(page, 'empty')
  await expect(page.getByText('No items on this queue page. No published corpus is required to upload and review filings.')).toBeVisible()
  await page.getByText('Upload a filing', { exact: true }).click()
  await expect(page.getByLabel('Original PDF (up to 64 MiB)', { exact: true })).toBeVisible()
})

test('learner access is denied before any private queue is displayed', async ({ page }) => {
  await setup(page, 'learner')
  await expect(page.getByRole('alert')).toContainText('Current administrator access is required')
  await expect(page.getByRole('navigation', { name: 'Administrator work queues' })).toHaveCount(0)
})

test('review keeps conditional support, renders the original and publishes separately', async ({ page }) => {
  const proof = await setup(page); await review(page)
  const panel = page.getByRole('region', { name: 'Candidate review', exact: true })
  await expect(panel.locator('blockquote').first()).toContainText('subject to approvals')
  await panel.getByText('All 16 validation checks', { exact: true }).click()
  await expect(panel.getByText('SOURCE · PASS', { exact: false })).toBeVisible()
  await panel.getByRole('button', { name: 'Inspect source 1', exact: true }).click()
  await expectRenderedSource(page)
  await expect(page.getByTestId('evidence-region')).toHaveCount(1)
  await note(page); await page.getByRole('button', { name: 'Record decision', exact: true }).click()
  await page.getByRole('button', { name: 'Add reviewed candidate to draft', exact: true }).click()
  await page.getByRole('button', { name: 'Check and create publication draft', exact: true }).click()
  await expect(page.getByText('Approved draft — publication pending', { exact: true })).toBeVisible()
  expect(proof.published).toBe(0)
  expect(proof.builds[0]?.selections[0]?.review_id).toBe(proof.reviews[0]?.id)
  await page.getByRole('button', { name: 'Publish this approved build', exact: true }).click()
  await expect(page.getByText('Published corpus', { exact: true })).toBeVisible()
  expect(proof.published).toBe(1)
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('quarantine cannot be approved and a rejection retains exact support', async ({ page }) => {
  const proof = await setup(page, 'quarantine'); await review(page)
  await page.getByLabel('Candidate state', { exact: true }).selectOption('QUARANTINED')
  await expect(page.getByLabel('Review decision', { exact: true }).locator('option[value="APPROVE_FOR_PUBLICATION"]')).toBeDisabled()
  await note(page); await page.getByRole('button', { name: 'Record decision', exact: true }).click()
  await expect(page.getByText('Recorded decision: REJECT', { exact: true })).toBeVisible()
  expect(proof.reviews[0]?.decision).toBe('REJECT')
  await expect(page.getByRole('button', { name: 'Add reviewed candidate to draft', exact: true })).toHaveCount(0)
})

test('a failed review response retries with the same immutable identity', async ({ page }) => {
  const proof = await setup(page, 'retry'); await review(page); await note(page)
  await page.getByRole('button', { name: 'Record decision', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('could not be completed')
  await expect(page.getByText('Recorded decision: APPROVE_FOR_PUBLICATION', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Record decision', exact: true }).click()
  await expect(page.getByText('Recorded decision: APPROVE_FOR_PUBLICATION', { exact: true })).toBeVisible()
  expect(proof.reviews).toHaveLength(2); expect(proof.reviews[0]?.id).toBe(proof.reviews[1]?.id)
})

test('role revocation clears loaded private review state', async ({ page }) => {
  const proof = await setup(page); await review(page); proof.revoked = true
  await page.getByRole('button', { name: 'Refresh queue', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign in as administrator', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Candidate review', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Administrator password', { exact: true })).toHaveValue('')
})

test('logout aborts a pending review and leaves no credential storage', async ({ page }) => {
  await setup(page, 'slow'); await review(page)
  await page.getByRole('button', { name: 'Sign out of administrator workspace', exact: true }).click()
  await page.waitForTimeout(600)
  await expect(page.getByRole('region', { name: 'Candidate review', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => Object.keys(localStorage).length + Object.keys(sessionStorage).length)).toBe(0)
  expect(page.url()).not.toContain('authored-password')
})

test('a changed original PDF hash prevents rendering', async ({ page }) => {
  await setup(page, 'bad-source'); await review(page)
  await page.getByRole('button', { name: 'Inspect source 1', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('source hash differs')
  await expect(page.getByRole('region', { name: 'Exact source page', exact: true })).toHaveCount(0)
})

test('amendment form preserves explicit scope and leaves an unsupported date empty', async ({ page }) => {
  const proof = await setup(page, 'amendment')
  await page.getByLabel('Record an evidence-backed amendment effect', { exact: true }).check()
  await page.getByLabel('Parent filing version', { exact: true }).fill(fixtures.evidence.data.record.source.filing_version_id)
  await page.getByLabel('Child filing version', { exact: true }).fill('00000000-0000-4000-8000-000000000001')
  await page.getByLabel('Issuer entity ID', { exact: true }).fill(fixtures.review_page.data.items[0]!.candidate.subject_entity_id)
  await page.getByLabel('Filing relationship', { exact: true }).selectOption('CORRIGENDUM_TO')
  await page.getByLabel('Effect', { exact: true }).selectOption('CORRECT')
  const source = fixtures.review_page.data.items[0]!.draft.supports[0]!
  for (const label of ['Parent issuer identity', 'Child issuer identity', 'Child reference to the parent filing', 'Exact support for this effect']) {
    const group = page.getByRole('group', { name: label, exact: true })
    await group.getByLabel('Evidence ID', { exact: true }).fill(source.evidence_id)
    await group.getByLabel('Start character (inclusive)', { exact: true }).fill(String(source.start))
    await group.getByLabel('End character (exclusive)', { exact: true }).fill(String(source.end))
    await group.getByLabel('Exact source quote', { exact: true }).fill(source.quote)
  }
  await page.getByLabel('Affected historical observation IDs', { exact: true }).fill(fixtures.manifest.data.observations[0]!.id)
  await page.getByLabel('New reviewed candidate IDs', { exact: true }).fill(fixtures.review_page.data.items[0]!.candidate.id)
  await page.getByLabel('Amendment review note', { exact: true }).fill('Authored explicit amendment support; no effective date inferred.')
  await page.getByRole('button', { name: 'Check and create publication draft', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('source or decision is invalid')
  expect(proof.builds[0]?.effects?.[0]?.effective_date).toBeNull()
  expect(proof.builds[0]?.effects?.[0]?.affected_observation_ids).toEqual([fixtures.manifest.data.observations[0]!.id])
  expect(proof.published).toBe(0)
})


test('PDF upload preserves explicit metadata and a parsed filing starts a tracked workflow', async ({ page }) => {
  const proof = await setup(page)
  await page.getByText('Upload a filing', { exact: true }).click()
  await page.getByLabel('Original PDF (up to 64 MiB)', { exact: true }).setInputFiles({
    name: 'authored-source.pdf', mimeType: 'application/pdf', buffer: Buffer.from(fixtures.pdf_base64, 'base64'),
  })
  await page.getByLabel('Company name as disclosed', { exact: true }).fill('Authored Alpha Energy')
  await page.getByLabel('Filing type', { exact: true }).selectOption('CORRIGENDUM')
  await page.getByRole('button', { name: 'Submit PDF for parsing', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Filing state: PARSED', exact: true })).toBeVisible()
  expect(proof.uploads).toEqual([{ company_name_raw: 'Authored Alpha Energy', document_type: 'CORRIGENDUM' }])
  await page.getByRole('button', { name: 'Refresh filing state', exact: true }).click()
  await page.getByLabel('Authored offering metric', { exact: true }).check()
  await page.getByRole('button', { name: 'Start extraction and validation', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Processing state: QUEUED', exact: true })).toBeVisible()
  expect(proof.processing[0]?.metric_ids).toEqual([fixtures.metrics.data.items[0]!.id])
  expect(proof.processing[0]?.parse_version_id).toBe(fixtures.filing_job.data.parse_version_id)
  await page.getByRole('button', { name: 'Dispatch pending workflow', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Pending workflow dispatched')
  await page.getByRole('button', { name: 'Refresh workflow', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Processing state: SUCCEEDED', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Dispatch pending workflow', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Review validated candidates', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Candidate review', exact: true })).toBeVisible()
})
