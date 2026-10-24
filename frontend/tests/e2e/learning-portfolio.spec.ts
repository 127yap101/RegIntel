import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { DefinitionDraft, OrderRequest, StoredDefinition } from '../../src/modules/generated'
import { definition, envelope, glossary, ids, opening, published, rejection, reviewed, user } from '../../src/modules/fixtures.test-support'
import { apiOrigin, webOrigin } from '../ports'

// Browser fixtures are authored engineering data, separate from real review/quotes.
async function authoredModules(page: Page, options: { admin?: boolean; empty?: boolean; loseResponse?: boolean; wrongVersion?: boolean } = {}) {
  let stored = structuredClone(definition) as unknown as StoredDefinition
  let available = !options.empty
  let accountCreated = false
  let recorded: OrderRequest | null = null
  const requests: OrderRequest[] = []
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    const headers = { 'Access-Control-Allow-Origin': webOrigin, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' }
    if (method === 'OPTIONS') { await route.fulfill({ status: 204, headers }); return }
    let data: unknown
    if (path === '/v1/auth/token') data = { access_token: 'authored-module-browser-token', token_type: 'bearer' }
    else if (path === '/v1/auth/me') data = envelope({ ...user, role: options.admin ? 'admin' : 'learner' })
    else if (path === '/v1/published-corpus') data = published.info
    else if (path === '/v1/companies') data = published.companies
    else if (path.endsWith('/facts')) data = published.facts
    else if (path === '/v1/learning/status') data = envelope({ state: available ? 'AVAILABLE' : 'NO_PUBLISHED_GLOSSARY', glossary_version_id: available ? ids.glossary : null }, { glossary_version_id: available ? ids.glossary : null })
    else if (path.startsWith('/v1/learning/glossary/')) data = envelope(glossary, { glossary_version_id: options.wrongVersion ? ids.account : ids.glossary })
    else if (path === '/v1/learning/drafts') {
      const input = route.request().postDataJSON() as DefinitionDraft
      expect(input.example).toEqual(definition.draft.example)
      stored = { ...stored, draft: { ...input, metric_ids: [] } }
      data = envelope(stored)
    } else if (path === `/v1/learning/drafts/${ids.definition}` && method === 'GET') data = envelope(stored)
    else if (path.endsWith('/review')) {
      if (method === 'GET') { await route.fulfill({ status: 200, headers, json: envelope({ ...reviewed, definition: stored }) }); return }
      expect(route.request().postDataJSON()).toEqual({ decision: 'APPROVE', note: 'Authored engineering review only.' })
      data = envelope({ ...reviewed, definition: stored })
    } else if (path === '/v1/learning/versions') {
      expect(route.request().postDataJSON()).toEqual({ definition_ids: [ids.definition], parent_glossary_version_id: null })
      available = true
      data = envelope({ ...glossary, definitions: [{ ...reviewed, definition: stored }] }, { glossary_version_id: ids.glossary })
    } else if (path === '/v1/learning/context') {
      expect(route.request().postDataJSON()).toMatchObject({ glossary_version_id: ids.glossary, definition_id: ids.definition, corpus_version_id: published.info.data.corpus_version_id, observation_id: published.facts.data.facts[0]!.observation.id })
      data = envelope({ glossary_version_id: ids.glossary, definition: reviewed, view: published.facts.data.view, observation: published.facts.data.facts[0]!.observation, evidence: [published.evidence.data], generated: false }, { glossary_version_id: ids.glossary, corpus_version_id: published.info.data.corpus_version_id })
    } else if (path === '/v1/portfolio/accounts') { accountCreated = true; data = envelope(opening, { portfolio_version_id: ids.account }) }
    else if (path === '/v1/portfolio' && accountCreated) data = envelope({ ...opening, committed_orders: recorded ? 1 : 0, portfolio_version_id: recorded ? ids.order : ids.account }, { portfolio_version_id: recorded ? ids.order : ids.account })
    else if (path === '/v1/portfolio/ledger' && accountCreated) data = envelope({ account_id: ids.account, portfolio_version_id: recorded ? ids.order : ids.account, entries: recorded ? [rejection(recorded).entry] : [], total: recorded ? 1 : 0, offset: 0 }, { portfolio_version_id: recorded ? ids.order : ids.account })
    else if (path === '/v1/portfolio/orders') {
      const input = route.request().postDataJSON() as OrderRequest
      requests.push(input)
      if (recorded) expect(input).toEqual(recorded)
      else recorded = input
      if (options.loseResponse && requests.length === 1) { await route.abort('failed'); return }
      data = envelope(rejection(input), { portfolio_version_id: ids.order, corpus_version_id: input.corpus_version_id })
    }
    await route.fulfill(data ? { status: 200, headers, json: data } : { status: 404, headers })
  })
  return requests
}

async function signIn(page: Page, mode: 'learning' | 'portfolio', reload = false) {
  if (!reload) await page.goto('/')
  await page.getByRole('link', { name: mode === 'learning' ? 'Financial learning' : 'Virtual portfolio', exact: true }).click()
  await page.getByLabel('Username', { exact: true }).fill('authored.learner')
  await page.getByLabel('Password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: `Sign in to ${mode === 'learning' ? 'financial learning' : 'virtual portfolio'}` }).click()
}

test('M3 administrator drafts an example, reviews and publishes without rendering filing/source text as HTML', async ({ page }) => {
  await authoredModules(page, { admin: true, empty: true }); await signIn(page, 'learning')
  await expect(page.getByText(/No glossary has been published/)).toBeVisible()
  await page.getByLabel('Term', { exact: true }).fill(definition.draft.term)
  await page.getByLabel('Source title', { exact: true }).fill('Authored source')
  await page.getByLabel('Definition', { exact: true }).last().fill(definition.draft.definition)
  await page.getByLabel('Source URL', { exact: true }).fill('https://example.test/learning')
  await page.getByLabel('Include an authored educational example').check()
  await page.getByLabel('Input unit', { exact: true }).fill('illustrative units')
  await page.getByLabel('Left decimal input', { exact: true }).fill('0.10')
  await page.getByLabel('Right decimal input', { exact: true }).fill('0.20')
  await page.getByLabel('Example explanation', { exact: true }).fill(definition.draft.example.explanation)
  await page.getByRole('button', { name: 'Save definition draft' }).click()
  await expect(page.getByRole('button', { name: 'Publish approved definition' })).toBeDisabled()
  await expect(page.getByText('left + right · inputs 0.10, 0.20 · result 0.30 illustrative units')).toBeVisible()
  await page.getByLabel('Review note', { exact: true }).fill('Authored engineering review only.')
  await page.getByRole('button', { name: 'Approve definition', exact: true }).click()
  await expect(page.getByText('Review recorded: APPROVE', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Load saved draft' }).click()
  await expect(page.getByRole('button', { name: 'Approve definition', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Publish approved definition' })).toBeEnabled()
  await page.getByRole('button', { name: 'Publish approved definition' }).click()
  const article = page.locator('article').filter({ has: page.getByRole('heading', { name: definition.draft.term }) })
  await expect(article).toContainText(definition.draft.definition)
  await expect(article.locator('script')).toHaveCount(0)
  await expect(article.getByRole('link', { name: 'Authored source' })).toHaveAttribute('rel', 'noopener noreferrer')
  expect(await page.evaluate(() => sessionStorage.length + localStorage.length)).toBe(0)
})

test('M3 learner sees reviewed source context and no authoring controls on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 })
  await authoredModules(page); await signIn(page, 'learning')
  await expect(page.getByRole('heading', { name: definition.draft.term })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save definition draft' })).toHaveCount(0)
  await page.getByRole('combobox', { name: 'Definition', exact: true }).selectOption(ids.definition)
  await page.getByRole('combobox', { name: 'Company', exact: true }).selectOption(published.companies.data.companies[0]!.id)
  await expect(page.getByRole('combobox', { name: 'Disclosure', exact: true }).locator('option')).toHaveCount(2)
  await page.getByRole('combobox', { name: 'Disclosure', exact: true }).selectOption(published.facts.data.facts[0]!.observation.id)
  await page.getByRole('button', { name: 'Show reviewed context' }).click()
  await expect(page.getByText(published.facts.data.facts[0]!.observation.raw_text, { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /View source page/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('M3 rejects a glossary envelope with another version', async ({ page }) => {
  await authoredModules(page, { wrongVersion: true }); await signIn(page, 'learning')
  await expect(page.getByRole('alert')).toContainText('glossary version changed')
  await expect(page.getByRole('heading', { name: definition.draft.term })).toHaveCount(0)
})

test('M4 keeps the exact request across a lost response and reload, then records one rejected order', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 })
  const requests = await authoredModules(page, { loseResponse: true }); await signIn(page, 'portfolio')
  await page.getByRole('button', { name: 'Create virtual account with INR 100000.00' }).click()
  await page.getByRole('combobox', { name: 'Published company', exact: true }).selectOption(published.companies.data.companies[0]!.id)
  await page.getByLabel('Whole shares', { exact: true }).fill('3')
  await page.getByRole('button', { name: 'Submit virtual order' }).click()
  await expect(page.getByRole('button', { name: 'Retry same virtual order' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit virtual order' })).toBeDisabled()
  await page.reload(); await signIn(page, 'portfolio', true)
  await page.getByRole('button', { name: 'Retry same virtual order' }).click()
  await expect(page.getByText('Recorded order #1: REJECTED · QUOTES UNAVAILABLE', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Virtual cash: INR 100000.00' })).toBeVisible()
  await expect(page.getByText('1 recorded orders · whole shares · zero fees', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry same virtual order' })).toHaveCount(0)
  expect(requests).toHaveLength(2)
  expect(requests[0]).toEqual(requests[1])
  expect(await page.evaluate(() => sessionStorage.length + localStorage.length)).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
