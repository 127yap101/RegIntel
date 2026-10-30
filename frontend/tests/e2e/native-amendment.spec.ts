import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import source from '../../src/admin/amendment.fixture.json' with { type: 'json' }
import existing from '../../src/admin/fixtures.generated.json' with { type: 'json' }
import type { PublicationRequest } from '../../src/admin/generated'
import { apiOrigin } from '../ports'
import { expectRenderedSource } from './pdf'

// Source-labelled actual PostgreSQL/HTTP correction fixture. Blank PDFs and
// authored word declarations are engineering data, not real filing review.
const accepted = source.accepted; const proposal = accepted.candidate.preparation.proposed_input
const lineage = source.request.lineages[0]!; const effect = source.request.effects[0]!
const gatePath = `/v1/admin/numerical/gates/${proposal.gate.id}`
type WordSupport = typeof lineage.parent_identity

async function setup(page: Page, mode: 'ready' | 'gap' | 'unavailable' | 'slow' = 'ready') {
  const state = { builds: [] as PublicationRequest[], published: 0, unavailable: mode === 'unavailable' }
  let approved = structuredClone(source.manifest)
  const headers = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'ETag,Content-Length' }
  const envelope = (data: unknown) => ({ data, meta: existing.identity.meta })
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname
    if (request.method() === 'OPTIONS') { await route.fulfill({ status: 204, headers: { ...headers, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' } }); return }
    if (path === '/v1/auth/token') { await route.fulfill({ headers, json: { access_token: 'authored-admin-token', token_type: 'bearer' } }); return }
    if (path === '/v1/auth/admin/me') { await route.fulfill({ headers, json: existing.identity }); return }
    expect(request.headers().authorization).toBe('Bearer authored-admin-token')
    if (path.includes('/queues/')) { const value = structuredClone(existing.queues.filings); Object.assign(value.data, { published_corpus_id: source.request.parent_corpus_version_id }); await route.fulfill({ headers, json: value }); return }
    if (path === gatePath) { await route.fulfill({ headers, json: envelope({ gate: proposal.gate, binding: proposal.proof, review: proposal.context_review }) }); return }
    if (path === gatePath + `/candidates/${accepted.candidate.record.id}`) { await route.fulfill({ headers, json: envelope(accepted.candidate) }); return }
    if (path === gatePath + `/candidates/${accepted.candidate.record.id}/acceptance`) { await route.fulfill({ headers, json: envelope(accepted) }); return }
    if (path.startsWith('/v1/evidence/')) {
      if (mode === 'slow') await new Promise((resolve) => setTimeout(resolve, 500))
      if (state.unavailable) { await route.fulfill({ status: 503, headers, json: {} }); return }
      const id = path.split('/').at(-1)!
      const value = (source.evidence as Record<string, unknown>)[id]
      try { await route.fulfill({ status: value ? 200 : 404, headers, json: value ?? {} }) } catch { /* Logout cancels pending source reads. */ }
      return
    }
    if (path.endsWith('/source.pdf')) {
      const id = path.split('/').at(-2)!
      const encoded = (source.pdfs as Record<string, string>)[id]!
      const bytes = Buffer.from(encoded, 'base64'); const filing = source.manifest.filings.find((filing) => filing.filing_version_id === id)!
      await route.fulfill({ headers: { ...headers, 'Content-Type': 'application/pdf', 'Content-Length': String(bytes.length), ETag: `"${filing.source_sha256}"` }, body: bytes }); return
    }
    if (path === '/v1/admin/publication/builds') {
      const body = request.postDataJSON() as PublicationRequest; state.builds.push(body)
      if (mode === 'gap') { await route.fulfill({ status: 422, headers, json: {} }); return }
      // Bind operator-generated decision IDs/notes to their actual submitted
      // source supports. All observation, source and acceptance data stays frozen.
      approved = structuredClone(source.manifest)
      Object.assign(approved.lineages[0]!, { proposal: body.lineages![0] })
      Object.assign(approved.effects[0]!, { proposal: body.effects![0] })
      await route.fulfill({ headers, json: envelope(approved) }); return
    }
    if (path === `/v1/admin/publication/builds/${source.manifest.id}/publish`) { state.published += 1; await route.fulfill({ headers, json: envelope(approved) }); return }
    await route.fulfill({ status: 404, headers, json: {} })
  })
  await page.goto('/')
  await page.getByRole('link', { name: 'Administrator workspace', exact: true }).click()
  await page.getByLabel('Administrator username', { exact: true }).fill('authored-admin')
  await page.getByLabel('Administrator password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: 'Sign in as administrator', exact: true }).click()
  return state
}

async function loadWords(group: Locator, value: WordSupport): Promise<void> {
  await group.getByLabel('Use ordered original words', { exact: true }).check()
  await group.getByLabel('Original word evidence IDs (source order)', { exact: true }).fill(value.spans.map((span) => span.evidence_id).join('\n'))
  await group.getByRole('button', { name: 'Load original words', exact: true }).click()
  await expect(group.locator('blockquote')).toHaveCount(value.spans.length)
}

async function prepare(page: Page, gap = false): Promise<void> {
  await page.getByRole('button', { name: 'Numerical filings', exact: true }).click()
  await page.getByLabel('Saved numerical gate ID', { exact: true }).fill(proposal.gate.id)
  await page.getByLabel('Saved numerical candidate ID (optional)', { exact: true }).fill(accepted.candidate.record.id)
  await page.getByRole('button', { name: 'Load numerical review', exact: true }).click()
  await page.getByRole('button', { name: 'Add accepted numerical candidate to draft', exact: true }).click()
  await page.getByLabel('Record an evidence-backed amendment effect', { exact: true }).check()
  await page.getByLabel('Parent filing version', { exact: true }).fill(lineage.parent_filing_version_id)
  await page.getByLabel('Child filing version', { exact: true }).fill(lineage.child_filing_version_id)
  await page.getByLabel('Issuer entity ID', { exact: true }).fill(lineage.issuer_entity_id)
  await page.getByLabel('Filing relationship', { exact: true }).selectOption('ADDENDUM_TO')
  await loadWords(page.getByRole('group', { name: 'Parent issuer identity', exact: true }), lineage.parent_identity)
  await loadWords(page.getByRole('group', { name: 'Child issuer identity', exact: true }), lineage.child_identity)
  await loadWords(page.getByRole('group', { name: 'Child reference to the parent filing', exact: true }), lineage.parent_reference)
  const statement = structuredClone(effect.supports[0]!)
  if (gap) statement.spans.splice(2, 1)
  await loadWords(page.getByRole('group', { name: 'Exact support for this effect', exact: true }), statement)
  await page.getByLabel('Affected historical observation IDs', { exact: true }).fill(effect.affected_observation_ids.join(','))
  await page.getByLabel('New reviewed candidate IDs', { exact: true }).fill(effect.new_candidate_ids.join(','))
  await page.getByLabel('Supported effective date (optional)', { exact: true }).fill(effect.effective_date)
  await loadWords(page.getByRole('group', { name: 'Exact support for the effective date', exact: true }), effect.effective_date_support)
  await page.getByLabel('Amendment review note', { exact: true }).fill(effect.review_note)
}

test('native amendment retains separate original words through explicit build and publish', async ({ page }) => {
  // This scenario assembles five source supports, inspects the PDF and publishes.
  // A trace showed the default total budget expiring after publication completed.
  test.setTimeout(60_000)
  const state = await setup(page); await prepare(page)
  await page.getByRole('button', { name: 'Check and create publication draft', exact: true }).click()
  const panel = page.getByRole('region', { name: 'Approved publication build', exact: true })
  await expect(panel.getByText('Approved draft — publication pending', { exact: true })).toBeVisible()
  const submitted = state.builds[0]!
  expect(submitted.lineages?.[0]?.parent_identity).toEqual(lineage.parent_identity)
  expect(submitted.effects?.[0]?.supports).toEqual(effect.supports)
  expect(submitted.effects?.[0]?.effective_date_support).toEqual(effect.effective_date_support)
  expect(submitted.parent_corpus_version_id).toBe(source.request.parent_corpus_version_id)
  await expect(panel.locator('blockquote').filter({ hasText: 'The earlier disclosure is corrected effective 1 January 2026.' })).toHaveCount(0)
  await panel.getByRole('button', { name: 'Inspect Effect 1 source 5', exact: true }).click()
  await expectRenderedSource(page)
  await expect(page.getByTestId('evidence-region')).toHaveCount(1)
  await page.getByRole('button', { name: 'Publish this approved build', exact: true }).click()
  await expect(panel.getByText('Published corpus', { exact: true })).toBeVisible()
  expect(state.published).toBe(1)
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('an operator gap remains a proposal and backend rejection cannot publish it', async ({ page }) => {
  const state = await setup(page, 'gap'); await prepare(page, true)
  await page.getByRole('button', { name: 'Check and create publication draft', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('invalid')
  await expect(page.getByRole('region', { name: 'Approved publication build', exact: true })).toHaveCount(0)
  expect(state.builds[0]?.effects?.[0]?.supports[0]).toEqual({ ...effect.supports[0], spans: effect.supports[0]!.spans.filter((_, index) => index !== 2) })
  expect(state.published).toBe(0)
})

test('failed word loading leaves no verified support and a later read can recover', async ({ page }) => {
  const state = await setup(page, 'unavailable')
  await page.getByLabel('Record an evidence-backed amendment effect', { exact: true }).check()
  const group = page.getByRole('group', { name: 'Parent issuer identity', exact: true })
  await group.getByLabel('Use ordered original words', { exact: true }).check()
  await group.getByLabel('Original word evidence IDs (source order)', { exact: true }).fill(lineage.parent_identity.spans.map((span) => span.evidence_id).join('\n'))
  await group.getByRole('button', { name: 'Load original words', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('could not be completed')
  await expect(group.locator('blockquote')).toHaveCount(0)
  state.unavailable = false
  await group.getByRole('button', { name: 'Load original words', exact: true }).click()
  await expect(group.locator('blockquote')).toHaveCount(lineage.parent_identity.spans.length)
  expect(state.builds).toHaveLength(0)
})

test('logout cancels word loading without restoring a private publication form', async ({ page }) => {
  await setup(page, 'slow')
  await page.getByLabel('Record an evidence-backed amendment effect', { exact: true }).check()
  const group = page.getByRole('group', { name: 'Parent issuer identity', exact: true })
  await group.getByLabel('Use ordered original words', { exact: true }).check()
  await group.getByLabel('Original word evidence IDs (source order)', { exact: true }).fill(lineage.parent_identity.spans.map((span) => span.evidence_id).join('\n'))
  await group.getByRole('button', { name: 'Load original words', exact: true }).click()
  await page.getByRole('button', { name: 'Sign out of administrator workspace', exact: true }).click()
  await page.waitForTimeout(600)
  await expect(page.getByRole('region', { name: 'Publication draft', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => Object.keys(localStorage).length + Object.keys(sessionStorage).length)).toBe(0)
})
