import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import analysis from '../../src/analysis/fixtures.generated.json' with { type: 'json' }
import { analytics, definition, envelope, glossary, ids, opening, rejection, reviewed, user } from '../../src/modules/fixtures.test-support'
import type { LearningContextRequest, OrderRequest } from '../../src/modules/generated'
import { apiOrigin, webOrigin } from '../ports'

const first = analysis.request.corpus_version_id
const later = '00000000-0000-4000-8000-000000000081'
const alpha = analysis.companies.data.companies.find((item) => item.name === 'Alpha Energy Limited')!
const alphaFacts = analysis.facts[alpha.id as keyof typeof analysis.facts]
const disclosure = alphaFacts.data.facts.find((item) => item.observation.kind === 'numeric_fact')!
const learningDefinition = { ...definition, draft: { ...definition.draft, metric_ids: [disclosure.metric.id] } }
const learningReview = { ...reviewed, definition: learningDefinition }
const learningVersion = { ...glossary, definitions: [learningReview] }

// These are authored fixture snapshots, never real filings, reviews or prices.
function atCorpus(value: unknown, corpus: string): unknown {
  if (Array.isArray(value)) return value.map((item) => atCorpus(item, corpus))
  if (value !== null && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, key === 'corpus_version_id' ? corpus : atCorpus(item, corpus)]))
  return value
}

async function movingHead(page: Page, loseFirstOrder = false) {
  const state = { headReads: 0, failure: null as 'unavailable' | 'mixed' | null }
  const companyReads: string[] = []
  const comparisons: string[] = []
  const contexts: LearningContextRequest[] = []
  const orders: OrderRequest[] = []
  let accountCreated = false
  let recorded: OrderRequest | null = null
  await page.route(`${apiOrigin}/v1/**`, async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    const headers = { 'Access-Control-Allow-Origin': webOrigin, 'Access-Control-Allow-Headers': 'authorization,content-type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' }
    if (method === 'OPTIONS') { await route.fulfill({ status: 204, headers }); return }
    const corpus = url.searchParams.get('corpus_version_id') ?? first
    let data: unknown
    if (path === '/v1/auth/token') data = { access_token: 'authored-shared-corpus-token', token_type: 'bearer' }
    else if (path === '/v1/auth/me') data = envelope(user)
    else if (path === '/v1/published-corpus') { state.headReads += 1; data = atCorpus(analysis.info, state.headReads === 1 ? first : later) }
    else if (path === '/v1/companies') {
      companyReads.push(corpus)
      if (state.failure === 'unavailable' && corpus === first) { await route.fulfill({ status: 404, headers }); return }
      data = atCorpus(analysis.companies, state.failure === 'mixed' && corpus === first ? later : corpus)
    } else if (path.endsWith('/facts') || path.endsWith('/graph')) {
      const company = path.split('/')[3]
      const selected = path.endsWith('/facts') ? analysis.facts[company as keyof typeof analysis.facts] : analysis.graphs[company as keyof typeof analysis.graphs]
      data = atCorpus(selected, corpus)
    } else if (path === '/v1/quotes') data = analysis.quotes
    else if (path === '/v1/compare') {
      const input = route.request().postDataJSON() as { corpus_version_id: string }
      expect(input).toEqual({ ...analysis.request, corpus_version_id: input.corpus_version_id })
      comparisons.push(input.corpus_version_id)
      data = atCorpus(analysis.comparison, input.corpus_version_id)
    } else if (path === '/v1/learning/status') data = envelope({ state: 'AVAILABLE', glossary_version_id: ids.glossary }, { glossary_version_id: ids.glossary })
    else if (path.startsWith('/v1/learning/glossary/')) data = envelope(learningVersion, { glossary_version_id: ids.glossary })
    else if (path === '/v1/learning/versions') data = envelope({ items: [{ glossary_version_id: ids.glossary, parent_glossary_version_id: null, definition_count: 1 }], head_glossary_version_id: ids.glossary, offset: 0, limit: 20, total: 1 })
    else if (path === '/v1/learning/context') {
      const input = route.request().postDataJSON() as LearningContextRequest
      contexts.push(input)
      expect(input).toMatchObject({ definition_id: ids.definition, glossary_version_id: ids.glossary, observation_id: disclosure.observation.id })
      const evidence = Object.values(analysis.evidence).filter((item) => item.data.observation_id === disclosure.observation.id).map((item) => item.data)
      expect(evidence.length).toBeGreaterThan(0)
      data = atCorpus(envelope({ glossary_version_id: ids.glossary, definition: learningReview, view: alphaFacts.data.view, observation: disclosure.observation, evidence, generated: false }, { glossary_version_id: ids.glossary, corpus_version_id: input.corpus_version_id }), input.corpus_version_id)
    } else if (path === '/v1/portfolio/accounts') { accountCreated = true; data = envelope(opening, { portfolio_version_id: ids.account }) }
    else if (path === '/v1/portfolio' && accountCreated) data = envelope({ ...opening, committed_orders: recorded ? 1 : 0, portfolio_version_id: recorded ? ids.order : ids.account }, { portfolio_version_id: recorded ? ids.order : ids.account })
    else if (path === '/v1/portfolio/ledger' && accountCreated) data = envelope({ account_id: ids.account, portfolio_version_id: recorded ? ids.order : ids.account, entries: recorded ? [rejection(recorded).entry] : [], total: recorded ? 1 : 0, offset: 0 }, { portfolio_version_id: recorded ? ids.order : ids.account })
    else if (path === '/v1/portfolio/analytics' && accountCreated) data = envelope({ ...analytics(recorded !== null), corpus_version_ids: recorded ? [recorded.corpus_version_id] : [] }, { portfolio_version_id: recorded ? ids.order : ids.account })
    else if (path === '/v1/portfolio/orders') {
      const input = route.request().postDataJSON() as OrderRequest
      orders.push(input)
      if (recorded) expect(input).toEqual(recorded)
      else recorded = input
      if (loseFirstOrder && orders.length === 1) { await route.abort('failed'); return }
      data = envelope(rejection(input), { portfolio_version_id: ids.order, corpus_version_id: input.corpus_version_id })
    }
    await route.fulfill(data ? { status: 200, headers, json: data } : { status: 404, headers })
  })
  return { state, companyReads, comparisons, contexts, orders }
}

async function explorerLogin(page: Page) {
  await page.getByLabel('Username', { exact: true }).fill('authored.learner')
  await page.getByLabel('Password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: 'Sign in to inspect filings', exact: true }).click()
  await expect(page.getByRole('button', { name: alpha.name, exact: true })).toBeVisible()
}

async function moduleLogin(page: Page, mode: 'learning' | 'portfolio') {
  await page.getByRole('link', { name: mode === 'learning' ? 'Financial learning' : 'Virtual portfolio', exact: true }).click()
  await page.getByLabel('Username', { exact: true }).fill('authored.learner')
  await page.getByLabel('Password', { exact: true }).fill('authored-password')
  await page.getByRole('button', { name: `Sign in to ${mode === 'learning' ? 'financial learning' : 'virtual portfolio'}`, exact: true }).click()
  await expect(page.getByText('Signed in as authored.learner', { exact: true })).toBeVisible()
}

async function compare(page: Page) {
  await page.getByRole('button', { name: alpha.name, exact: true }).click()
  await page.getByRole('checkbox', { name: alpha.name, exact: true }).check()
  await page.getByRole('checkbox', { name: 'Beta Solar Limited', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Revenue (authored fixture)', exact: true }).check()
  await page.getByLabel('Period start', { exact: true }).fill('2025-04-01')
  await page.getByLabel('Period end', { exact: true }).fill('2026-03-31')
  await page.getByRole('button', { name: 'Compare published values', exact: true }).click()
  await expect(page.getByRole('table')).toBeVisible()
}

async function explain(page: Page) {
  await page.getByRole('combobox', { name: 'Definition', exact: true }).selectOption(ids.definition)
  await page.getByRole('combobox', { name: 'Company', exact: true }).selectOption(alpha.id)
  await page.getByRole('combobox', { name: 'Disclosure', exact: true }).selectOption(disclosure.observation.id)
  await page.getByRole('button', { name: 'Show reviewed context', exact: true }).click()
  await expect(page.getByText('Original published disclosure · no generated paraphrase', { exact: true })).toBeVisible()
}

async function submit(page: Page) {
  await page.getByRole('button', { name: 'Create virtual account with INR 100000.00', exact: true }).click()
  await page.getByRole('combobox', { name: 'Published company', exact: true }).selectOption(alpha.id)
  await page.getByRole('button', { name: 'Submit virtual order', exact: true }).click()
}

test('M1–M4 keep one corpus when a newer head appears between workspace visits', async ({ page }) => {
  const calls = await movingHead(page)
  await page.goto('/'); await explorerLogin(page); await compare(page)
  await moduleLogin(page, 'learning'); await explain(page)
  await page.getByRole('link', { name: 'Virtual portfolio', exact: true }).click()
  await submit(page)
  await expect(page.getByText(/Recorded order #1: REJECTED/)).toBeVisible()
  expect(calls.state.headReads).toBe(1)
  expect(calls.companyReads.every((identity) => identity === first)).toBe(true)
  expect(calls.comparisons).toEqual([first])
  expect(calls.contexts.map((value) => value.corpus_version_id)).toEqual([first])
  expect(calls.orders.map((value) => value.corpus_version_id)).toEqual([first])
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})

test('an explicit latest-corpus choice clears old M2 results and carries the new version to learning', async ({ page }) => {
  const calls = await movingHead(page)
  await page.goto('/'); await explorerLogin(page); await compare(page)
  await page.getByRole('button', { name: 'Use latest published corpus', exact: true }).click()
  await expect(page.getByText(`Viewing corpus: ${later}`, { exact: true })).toBeVisible()
  await expect(page.getByRole('table')).toHaveCount(0)
  await moduleLogin(page, 'learning'); await explain(page)
  expect(calls.state.headReads).toBe(2)
  expect(calls.contexts.map((value) => value.corpus_version_id)).toEqual([later])
})

for (const failure of ['unavailable', 'mixed'] as const) {
  test(`a ${failure} selected corpus cannot silently switch M3/M4 to a newer head`, async ({ page }) => {
    const calls = await movingHead(page)
    await page.goto('/'); await explorerLogin(page)
    calls.state.failure = failure
    await moduleLogin(page, 'learning')
    await expect(page.getByText(/selected filing corpus could not be verified/)).toBeVisible()
    await expect(page.getByText(learningDefinition.draft.definition, { exact: true })).toBeVisible()
    await page.getByRole('link', { name: 'Virtual portfolio', exact: true }).click()
    await page.getByRole('button', { name: 'Create virtual account with INR 100000.00', exact: true }).click()
    await expect(page.getByText(/selected filing corpus could not be verified/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Submit virtual order', exact: true })).toBeDisabled()
    expect(calls.state.headReads).toBe(1)
    expect(calls.orders).toEqual([])
    await page.getByRole('link', { name: 'Explore published filings', exact: true }).click()
    await page.getByRole('button', { name: 'Use latest corpus at next sign-in', exact: true }).click()
    await explorerLogin(page)
    await expect(page.getByText(`Viewing corpus: ${later}`, { exact: true })).toBeVisible()
    expect(calls.state.headReads).toBe(2)
  })
}

test('sign-out clears the page-session corpus without storing credentials or the selection', async ({ page }) => {
  const calls = await movingHead(page)
  await page.goto('/'); await moduleLogin(page, 'learning')
  await expect(page.getByText(new RegExp(`Selected filing corpus: ${first}`))).toBeVisible()
  await page.getByRole('button', { name: 'Sign out of learning and portfolio', exact: true }).click()
  await page.getByRole('link', { name: 'Explore published filings', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Use latest corpus at next sign-in', exact: true })).toHaveCount(0)
  await explorerLogin(page)
  await expect(page.getByText(`Viewing corpus: ${later}`, { exact: true })).toBeVisible()
  expect(calls.state.headReads).toBe(2)
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})

test('a lost-response retry retains its original corpus after the page selects a newer one', async ({ page }) => {
  const calls = await movingHead(page, true)
  await page.goto('/'); await moduleLogin(page, 'portfolio'); await submit(page)
  await expect(page.getByRole('button', { name: 'Retry same virtual order', exact: true })).toBeVisible()
  await page.reload(); await moduleLogin(page, 'portfolio')
  await expect(page.getByText(/pending request retains its original filing corpus/)).toBeVisible()
  await page.getByRole('button', { name: 'Retry same virtual order', exact: true }).click()
  await expect(page.getByText(/Recorded order #1: REJECTED/)).toBeVisible()
  expect(calls.orders).toHaveLength(2)
  expect(calls.orders[0]).toEqual(calls.orders[1])
  expect(calls.orders[0]?.corpus_version_id).toBe(first)
  expect(calls.state.headReads).toBe(2)
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0)
})
