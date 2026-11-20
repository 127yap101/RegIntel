import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import base from '../../src/admin/numerical.fixture.json' with { type: 'json' }
import workspace from '../../src/admin/fixtures.generated.json' with { type: 'json' }
import type { NumericalRefreshRequest } from '../../src/admin/generated'
import { apiOrigin } from '../ports'

const source = base.manifest.new_acceptances[0]!.accepted.candidate.preparation.proposed_input
const gateId = source.gate.id
const refreshedId = '00000000-0000-4000-8000-000000000001'

async function setup(page: Page, mode: 'refresh' | 'unchanged' | 'retry' | 'mismatch') {
  const requests: NumericalRefreshRequest[] = []
  const otherWrites: string[] = []
  const old = structuredClone({ gate: source.gate, binding: source.proof, review: null })
  const next = structuredClone(old)
  if (mode !== 'unchanged') {
    next.gate.id = refreshedId
    next.gate.context_record_id = '00000000-0000-4000-8000-000000000002'
    next.binding.context_record_id = next.gate.context_record_id
    next.binding.id = '00000000-0000-4000-8000-000000000003'
    next.gate.evidence_binding_id = next.binding.id
    next.gate.input_sha256 = 'b'.repeat(64)
  }
  const envelope = (data: unknown) => ({ data, meta: base.private_meta })
  const headers = { 'Access-Control-Allow-Origin': '*' }
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname
    if (request.method() === 'OPTIONS') { await route.fulfill({ status: 204, headers: { ...headers, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' } }); return }
    if (path === '/v1/auth/token') { await route.fulfill({ headers, json: { access_token: 'authored-token', token_type: 'bearer' } }); return }
    if (path === '/v1/auth/admin/me') { await route.fulfill({ headers, json: workspace.identity }); return }
    if (path.includes('/queues/')) { await route.fulfill({ headers, json: workspace.queues.filings }); return }
    if (path === `/v1/admin/numerical/gates/${gateId}`) { await route.fulfill({ headers, json: envelope(old) }); return }
    if (path === `/v1/admin/numerical/gates/${gateId}/refresh`) {
      const body = request.postDataJSON() as NumericalRefreshRequest; requests.push(body)
      expect(body.gate_run_id).toBe(gateId)
      expect(body.gate_input_sha256).toBe(source.gate.input_sha256)
      expect(body.gate_result_sha256).toBe(source.context_review.gate_result_sha256)
      if (mode === 'retry' && requests.length === 1) { await route.abort('failed'); return }
      const packet = structuredClone(next)
      if (mode === 'mismatch') packet.binding.cells[0]!.column_index += 1
      await route.fulfill({ headers, json: envelope({ schema_version: 'numerical-refresh-result-1', request: body, previous_context_record_id: old.gate.context_record_id, context_changed: mode !== 'unchanged', gate_changed: mode !== 'unchanged', packet, acceptance_eligible: false, mandatory_m1_validation_complete: false, publishes_fact: false }) }); return
    }
    if (request.method() === 'POST') otherWrites.push(path)
    await route.fulfill({ status: 404, headers, json: {} })
  })
  await page.goto('/admin')
  await page.getByLabel('Administrator username', { exact: true }).fill('authored-admin')
  await page.getByLabel('Administrator password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: 'Sign in as administrator', exact: true }).click()
  await page.getByRole('button', { name: 'Numerical filings', exact: true }).click()
  await page.getByLabel('Saved numerical gate ID', { exact: true }).fill(gateId)
  await page.getByRole('button', { name: 'Load numerical review', exact: true }).click()
  await expect(page.getByText(`Gate ${gateId} · Parse ${source.gate.parse_version_id}`, { exact: true })).toBeVisible()
  return { requests, otherWrites }
}

for (const mode of ['refresh', 'unchanged', 'retry', 'mismatch'] as const) {
  test(`numerical ${mode} preserves exact source selection and creates no review`, async ({ page }) => {
    const state = await setup(page, mode)
    await page.getByRole('button', { name: 'Refresh source and approval checks', exact: true }).click()
    if (mode === 'retry' || mode === 'mismatch') {
      await expect(page.getByRole('button', { name: 'Retry the same source refresh', exact: true })).toBeEnabled()
      await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toBeDisabled()
      await expect(page.getByRole('button', { name: 'Record context decision', exact: true })).toBeDisabled()
      if (mode === 'retry') await page.getByRole('button', { name: 'Retry the same source refresh', exact: true }).click()
    }
    if (mode !== 'mismatch') {
      await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toHaveValue(mode === 'unchanged' ? gateId : refreshedId)
      await expect(page.getByText(mode === 'unchanged' ? 'Current checks match this saved gate. No review or financial approval was created.' : `Opened refreshed checks. Previous gate ${gateId} remains in history. No review or financial approval was created.`, { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Refresh source and approval checks', exact: true })).toBeEnabled()
    } else await expect(page.getByLabel('Saved numerical gate ID', { exact: true })).toHaveValue(gateId)
    expect(state.otherWrites).toEqual([])
    expect(state.requests).toHaveLength(mode === 'retry' ? 2 : 1)
    if (mode === 'retry') expect(state.requests[1]).toEqual(state.requests[0])
  })
}
