import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import fixture from '../../src/admin/numerical.fixture.json' with { type: 'json' }
import existing from '../../src/admin/fixtures.generated.json' with { type: 'json' }
import type { NumericalAcceptanceRequest, NumericalCandidateRequest, NumericalContextReviewRequest, PublicationRequest } from '../../src/admin/generated'
import { apiOrigin } from '../ports'
import { expectRenderedSource } from './pdf'

// Actual retained HTTP/build shapes over authored blank-PDF/word declarations.
// These browser routes are engineering scenarios, not real financial approvals.
const accepted = fixture.manifest.new_acceptances[0]!.accepted
const proposed = accepted.candidate.preparation.proposed_input
const gateId = proposed.gate.id; const candidateId = accepted.candidate.record.id
const root = `/v1/admin/numerical/gates/${gateId}`
type Mode = 'ready' | 'blocked-gate' | 'blocked-preparation' | 'restore' | 'retry-context' | 'retry-candidate' | 'retry-acceptance' | 'unavailable-acceptance' | 'conflict' | 'source-configuration' | 'source-geometry' | 'bad-hash' | 'mixed-packet' | 'slow'

async function setup(page: Page, mode: Mode = 'ready') {
  const state = { revoked: false, context: mode === 'restore', candidate: mode === 'restore', accepted: mode === 'restore', rejectedContext: false, rejectedCandidate: false,
    reviews: [] as NumericalContextReviewRequest[], candidates: [] as NumericalCandidateRequest[], decisions: [] as NumericalAcceptanceRequest[], builds: [] as PublicationRequest[], published: 0, acceptanceReads: 0 }
  const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'ETag,Content-Length' }
  const envelope = (data: unknown) => ({ data, meta: fixture.private_meta })
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname
    if (request.method() === 'OPTIONS') { await route.fulfill({ status: 204, headers: { ...headers, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' } }); return }
    if (path === '/v1/auth/token') { await route.fulfill({ headers, json: { access_token: 'authored-admin-token', token_type: 'bearer' } }); return }
    if (path === '/v1/auth/admin/me') { await route.fulfill({ headers, json: existing.identity }); return }
    expect(request.headers().authorization).toBe('Bearer authored-admin-token')
    if (state.revoked) { await route.fulfill({ status: 403, headers, json: {} }); return }
    if (path.includes('/queues/')) { await route.fulfill({ headers, json: existing.queues.filings }); return }
    if (path === root) {
      if (mode === 'slow') await new Promise((resolve) => setTimeout(resolve, 500))
      const value = structuredClone({ gate: proposed.gate, binding: proposed.proof, review: state.context ? proposed.context_review : null })
      if (mode === 'blocked-gate') { value.gate.state = 'REVIEW_REQUIRED'; value.gate.checks.find((check) => check.code === 'UNIT')!.state = 'REVIEW' }
      if (state.rejectedContext && value.review) value.review.request.decision = 'REJECT'
      if (mode === 'mixed-packet') value.gate.evidence_ids.pop()
      try { await route.fulfill({ headers, json: envelope(value) }) } catch { /* Logout deliberately cancels this source read. */ }
      return
    }
    if (path === root + '/review') {
      const body = request.postDataJSON() as NumericalContextReviewRequest; state.reviews.push(body); state.context = true; state.rejectedContext = body.decision === 'REJECT'
      if (mode === 'retry-context' && state.reviews.length === 1) { await route.fulfill({ status: 503, headers, json: {} }); return }
      const value = structuredClone(proposed.context_review); Object.assign(value, { request: body })
      await route.fulfill({ headers, json: envelope(value) }); return
    }
    if (path === root + '/publication-input') {
      const value = structuredClone(accepted.candidate.preparation)
      if (mode === 'blocked-preparation') { value.state = 'BLOCKED'; value.checks[0]!.state = 'FAIL'; Object.assign(value, { proposed_input: null }) }
      await route.fulfill({ headers, json: envelope(value) }); return
    }
    if (path === root + '/candidates' || path === root + `/candidates/${candidateId}`) {
      if (request.method() === 'POST') {
        const body = request.postDataJSON() as NumericalCandidateRequest; state.candidates.push(body); state.candidate = true
        expect(body).toEqual(accepted.candidate.record.request)
        if (mode === 'retry-candidate' && state.candidates.length === 1) { await route.fulfill({ status: 503, headers, json: {} }); return }
      }
      await route.fulfill({ status: state.candidate ? 200 : 404, headers, json: envelope(accepted.candidate) }); return
    }
    if (path === root + `/candidates/${candidateId}/acceptance`) {
      if (request.method() === 'POST') {
        const body = request.postDataJSON() as NumericalAcceptanceRequest; state.decisions.push(body)
        if (mode === 'conflict' && state.decisions.length === 1) { await route.fulfill({ status: 409, headers, json: {} }); return }
        state.accepted = true; state.rejectedCandidate = body.decision === 'REJECT'
        if (mode === 'retry-acceptance' && state.decisions.length === 1) { await route.fulfill({ status: 503, headers, json: {} }); return }
      } else {
        state.acceptanceReads += 1
        if (mode === 'unavailable-acceptance' && state.acceptanceReads === 1) { await route.fulfill({ status: 503, headers, json: {} }); return }
      }
      const value = structuredClone(accepted)
      if (state.decisions[0]) Object.assign(value.record, { request: state.decisions[0] })
      if (state.rejectedCandidate) { value.record.state = 'REJECTED'; value.record.mandatory_m1_validation_complete = false; value.record.checks = [] }
      await route.fulfill({ status: state.accepted ? 200 : 404, headers, json: envelope(value) }); return
    }
    if (path === '/v1/admin/publication/builds') { const body = request.postDataJSON() as PublicationRequest; state.builds.push(body); await route.fulfill({ headers, json: envelope(fixture.manifest) }); return }
    if (path === `/v1/admin/publication/builds/${fixture.manifest.id}/publish`) { state.published += 1; await route.fulfill({ headers, json: envelope(fixture.manifest) }); return }
    if (path.startsWith('/v1/evidence/')) {
      const value = structuredClone(fixture.evidence)
      if (mode === 'source-configuration') value.data.processing_configuration_sha256 = 'e'.repeat(64)
      if (mode === 'source-geometry') value.data.record.boxes[0]!.x0 += 0.25
      await route.fulfill({ headers, json: value }); return
    }
    if (path.endsWith('/source.pdf')) {
      const bytes = Buffer.from(fixture.pdf_base64, 'base64'); if (mode === 'bad-hash') bytes[bytes.length - 1] = bytes[bytes.length - 1]! ^ 1
      await route.fulfill({ headers: { ...headers, 'Content-Type': 'application/pdf', 'Content-Length': String(bytes.length), ETag: `"${fixture.evidence.data.source_sha256}"` }, body: bytes }); return
    }
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

async function load(page: Page, restore = false): Promise<void> {
  await page.getByLabel('Saved numerical gate ID', { exact: true }).fill(gateId)
  if (restore) await page.getByLabel('Saved numerical candidate ID (optional)', { exact: true }).fill(candidateId)
  await page.getByRole('button', { name: 'Load numerical review', exact: true }).click()
}
async function confirm(page: Page): Promise<void> {
  await page.getByLabel('Numerical context decision', { exact: true }).selectOption('CONFIRM_CONTEXT')
  await page.getByLabel('Context review note', { exact: true }).fill(proposed.context_review.request.note)
  await page.getByRole('button', { name: 'Record context decision', exact: true }).click()
}
async function save(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Check current candidate prerequisites', exact: true }).click()
  await page.getByRole('button', { name: 'Save numerical candidate', exact: true }).click()
}
async function accept(page: Page, decision: 'ACCEPT' | 'REJECT' = 'ACCEPT'): Promise<void> {
  await page.getByLabel('Numerical acceptance decision', { exact: true }).selectOption(decision)
  await page.getByLabel('Numerical acceptance note', { exact: true }).fill(accepted.record.request.note)
  await page.getByRole('button', { name: 'Record numerical acceptance decision', exact: true }).click()
}

test('numerical review inspects separate original words and publishes an explicitly accepted candidate', async ({ page }) => {
  const state = await setup(page); await load(page)
  const panel = page.getByRole('region', { name: 'Numerical filing review', exact: true })
  await expect(panel.getByText('2500.20', { exact: true })).toBeVisible()
  await panel.getByText('Original source words and table context', { exact: true }).click()
  await panel.getByRole('button', { name: 'Inspect original word 1 in value 1', exact: true }).click()
  await expectRenderedSource(page)
  await expect(page.getByRole('heading', { name: 'Source page 2', exact: true })).toBeVisible()
  await expect(page.getByTestId('evidence-region')).toHaveCount(1)
  await confirm(page); await save(page); await accept(page)
  await page.getByRole('button', { name: 'Add accepted numerical candidate to draft', exact: true }).click()
  await page.getByRole('button', { name: 'Check and create publication draft', exact: true }).click()
  await expect(page.getByText('Approved draft — publication pending', { exact: true })).toBeVisible()
  expect(state.published).toBe(0)
  expect(state.builds[0]?.selections).toEqual([{ candidate_run_id: gateId, candidate_id: candidateId, review_id: accepted.record.id }])
  await page.getByRole('button', { name: 'Publish this approved build', exact: true }).click()
  await expect(page.getByText('Published corpus', { exact: true })).toBeVisible()
  expect(state.published).toBe(1)
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('an unresolved gate cannot be confirmed and records an explicit rejection', async ({ page }) => {
  const state = await setup(page, 'blocked-gate'); await load(page)
  await expect(page.getByLabel('Numerical context decision', { exact: true }).locator('option[value="CONFIRM_CONTEXT"]')).toBeDisabled()
  await page.getByLabel('Context review note', { exact: true }).fill('Authored unresolved unit; explicitly rejected.')
  await page.getByRole('button', { name: 'Record context decision', exact: true }).click()
  await expect(page.getByText('Recorded context decision: REJECT', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Check current candidate prerequisites', exact: true })).toHaveCount(0)
  expect(state.reviews[0]?.decision).toBe('REJECT'); expect(state.candidates).toHaveLength(0)
})

test('review notes remain inert text when retained in the source audit', async ({ page }) => {
  const state = await setup(page); await load(page)
  const note = '<img src="invalid" onerror="document.body.dataset.numericalInjected=1"> Authored review note.'
  await page.getByLabel('Context review note', { exact: true }).fill(note)
  await page.getByRole('button', { name: 'Record context decision', exact: true }).click()
  await expect(page.getByText(note, { exact: true })).toBeVisible()
  expect(state.reviews[0]?.note).toBe(note)
  expect(await page.locator('body').getAttribute('data-numerical-injected')).toBeNull()
  await expect(page.getByRole('region', { name: 'Numerical filing review', exact: true }).locator('img')).toHaveCount(0)
})

test('a blocked fresh preparation exposes its checks and creates no candidate', async ({ page }) => {
  const state = await setup(page, 'blocked-preparation'); await load(page); await confirm(page)
  await page.getByRole('button', { name: 'Check current candidate prerequisites', exact: true }).click()
  await expect(page.getByText('Current preparation: BLOCKED', { exact: true })).toBeVisible()
  await page.getByText('All 16 candidate validation checks', { exact: true }).click()
  await expect(page.getByText('SOURCE · FAIL', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save numerical candidate', exact: true })).toHaveCount(0)
  expect(state.candidates).toHaveLength(0)
})

test('candidate rejection cannot enter the publication selection', async ({ page }) => {
  const state = await setup(page); await load(page); await confirm(page); await save(page); await accept(page, 'REJECT')
  await expect(page.getByText('Recorded numerical decision: REJECT', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add accepted numerical candidate to draft', exact: true })).toHaveCount(0)
  expect(state.decisions[0]?.decision).toBe('REJECT'); expect(state.builds).toHaveLength(0)
})

for (const kind of ['context', 'candidate', 'acceptance'] as const) test(`lost ${kind} response locks fields and retries the exact submitted request`, async ({ page }) => {
  const state = await setup(page, `retry-${kind}`); await load(page); await confirm(page)
  if (kind !== 'context') await save(page)
  if (kind === 'acceptance') await accept(page)
  await expect(page.getByRole('alert')).toContainText('could not be completed')
  await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Filing jobs', exact: true })).toBeDisabled()
  if (kind === 'context') await expect(page.getByLabel('Context review note', { exact: true })).toBeDisabled()
  if (kind === 'acceptance') await expect(page.getByLabel('Numerical acceptance note', { exact: true })).toBeDisabled()
  await page.getByRole('button', { name: kind === 'context' ? 'Retry the same context decision' : kind === 'candidate' ? 'Retry the same candidate request' : 'Retry the same acceptance decision', exact: true }).click()
  await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toBeEnabled()
  const submitted = kind === 'context' ? state.reviews : kind === 'candidate' ? state.candidates : state.decisions
  expect(submitted).toHaveLength(2); expect(submitted[0]).toEqual(submitted[1])
})

test('acceptance storage failure after candidate creation stays unresolved until a verified retry', async ({ page }) => {
  const state = await setup(page, 'unavailable-acceptance'); await load(page); await confirm(page); await save(page)
  await expect(page.getByRole('alert')).toContainText('could not be completed')
  await expect(page.getByRole('region', { name: 'Numerical candidate acceptance', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Retry the same candidate request', exact: true }).click()
  await expect(page.getByLabel('Numerical acceptance note', { exact: true })).toBeVisible()
  expect(state.candidates).toHaveLength(2); expect(state.candidates[0]).toEqual(state.candidates[1])
  expect(state.decisions).toHaveLength(0)
})

test('explicit conflict unlocks correction and stored-history inspection', async ({ page }) => {
  await setup(page, 'conflict'); await load(page); await confirm(page); await save(page); await accept(page)
  await expect(page.getByRole('alert')).toContainText('conflicts with stored history')
  await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Load numerical review', exact: true }).click()
  await expect(page.getByLabel('Numerical acceptance note', { exact: true })).toBeVisible()
})

test('saved candidate and decision restore without resubmitting approval or publication', async ({ page }) => {
  const state = await setup(page, 'restore'); await load(page, true)
  await expect(page.getByText('Recorded context decision: CONFIRM_CONTEXT', { exact: true })).toBeVisible()
  await expect(page.getByText('Recorded numerical decision: ACCEPT', { exact: true })).toBeVisible()
  await expect(page.getByText('Stored preparation snapshot: READY_FOR_ADAPTER', { exact: true })).toBeVisible()
  expect(state.reviews).toHaveLength(0); expect(state.candidates).toHaveLength(0); expect(state.decisions).toHaveLength(0); expect(state.published).toBe(0)
})

for (const mode of ['source-configuration', 'source-geometry', 'bad-hash'] as const) test(`changed ${mode} prevents original source rendering`, async ({ page }) => {
  await setup(page, mode); await load(page)
  await page.getByText('Original source words and table context', { exact: true }).click()
  await page.getByRole('button', { name: 'Inspect original word 1 in value 1', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText(mode === 'bad-hash' ? 'source hash differs' : 'original word, PDF or parse configuration differs')
  await expect(page.getByRole('region', { name: 'Exact source page', exact: true })).toHaveCount(0)
})

test('mixed gate support is never displayed as a reviewable proposal', async ({ page }) => {
  await setup(page, 'mixed-packet'); await load(page)
  await expect(page.getByRole('alert')).toContainText('could not be verified')
  await expect(page.getByRole('region', { name: 'Numerical context review', exact: true })).toHaveCount(0)
})

test('current-admin revocation clears numerical proposals and notes', async ({ page }) => {
  const state = await setup(page); await load(page); await confirm(page); state.revoked = true
  await page.getByRole('button', { name: 'Check current candidate prerequisites', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign in as administrator', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Numerical filing review', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Administrator password', { exact: true })).toHaveValue('')
})

test('logout cancels a pending numerical read and leaves no browser credential storage', async ({ page }) => {
  await setup(page, 'slow'); await load(page)
  await page.getByRole('button', { name: 'Sign out of administrator workspace', exact: true }).click()
  await page.waitForTimeout(600)
  await expect(page.getByRole('region', { name: 'Numerical filing review', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => Object.keys(localStorage).length + Object.keys(sessionStorage).length)).toBe(0)
})
