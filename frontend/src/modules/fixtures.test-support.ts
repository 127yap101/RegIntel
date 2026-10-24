// Authored engineering scenarios only. None is a real definition approval or quote.
import published from '../published/fixtures.generated.json' with { type: 'json' }

export { published }
export const ids = {
  user: '00000000-0000-4000-8000-000000000071',
  definition: '00000000-0000-4000-8000-000000000072',
  review: '00000000-0000-4000-8000-000000000073',
  glossary: '00000000-0000-4000-8000-000000000074',
  account: '00000000-0000-4000-8000-000000000075',
  order: '00000000-0000-4000-8000-000000000076',
  request: '00000000-0000-4000-8000-000000000077',
}
export function envelope(data: unknown, versions: Record<string, string | null> = {}) {
  return { data, meta: { contract_version: '1.0.0', request_id: ids.request, versions: { corpus_version_id: null, filing_version_id: null, parse_version_id: null, glossary_version_id: null, portfolio_version_id: null, quote_version_id: null, ...versions } } }
}
export const user = { id: ids.user, username: 'authored.learner', role: 'learner' }
export const example = { kind: 'AUTHORED_EDUCATIONAL_EXAMPLE', operation: 'ADD', left: '0.10', right: '0.20', unit: 'illustrative units', explanation: 'Authored arithmetic example, not a filing claim.' }
export const definition = {
  id: ids.definition, content_sha256: 'e'.repeat(64), submitted_by: ids.user,
  draft: { term: 'Authored learning term', definition: 'Authored definition <script>untrusted text</script>; no real approval.', sources: [{ title: 'Authored source', url: 'https://example.test/learning', location: null }], metric_ids: [published.facts.data.facts[0]!.observation.metric_id], example },
  calculation: { input: example, state: 'AVAILABLE', result: '0.30', result_unit: 'illustrative units', formula: 'left + right', rounding: 'EXACT' },
}
export const reviewed = { definition, review_id: ids.review, reviewed_by: ids.user, review: { decision: 'APPROVE', note: 'Authored engineering review only.' } }
export const glossary = { glossary_version_id: ids.glossary, parent_glossary_version_id: null, definitions: [reviewed] }
export const opening = { account_id: ids.account, portfolio_version_id: ids.account, state: { cash: '100000.00', currency: 'INR', holdings: [] }, committed_orders: 0, valuation_state: 'UNAVAILABLE', market_value: null, total_value: null }
export const request = { request_id: ids.request, corpus_version_id: published.info.data.corpus_version_id, company_id: published.companies.data.companies[0]!.id, side: 'BUY', quantity: 3 }
export function rejection(input: unknown = request) {
  return { account_id: ids.account, portfolio_version_id: ids.order, entry: { id: ids.order, sequence: 1, request: input, quote: null, committed_at: '2026-10-24T06:00:00Z', evaluation: { state: 'REJECTED', reason: 'QUOTES_UNAVAILABLE', before: opening.state, after: opening.state, cash_delta: '0.00', quantity_delta: 0 } } }
}
