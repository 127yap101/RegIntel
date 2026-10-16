import { useState } from 'react'
import type { AnswerInput, AnswerResult } from './wire'
import { Button } from '../components/Button'
import { FinancialContext } from '../published/FinancialContext'

export function AnswerPanel({ answer, busy, ask, inspect }: { answer: AnswerResult | null; busy: boolean; ask: (input: AnswerInput) => void; inspect: (observation: string, evidence: string) => void }) {
  const [question, setQuestion] = useState('')
  const [arm, setArm] = useState<AnswerInput['arm']>('B3')
  return <section aria-label="Questions about published filings" className="mt-7 rounded-xl border border-line bg-white p-5">
    <h3 className="text-lg font-semibold">Find evidence in filings</h3>
    <p className="mt-2 text-sm leading-6 text-muted">Ask about reviewed disclosures in this corpus. Results quote the original source and retain its conditions. Missing support returns an explicit unavailable result.</p>
    <form className="mt-4 space-y-4" onSubmit={(event) => { event.preventDefault(); ask({ question, arm }) }}>
      <label htmlFor="filing-question" className="block text-sm font-medium">Question</label>
      <textarea id="filing-question" required maxLength={1000} rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} className="mt-2 block w-full rounded-lg border border-line p-3" placeholder="What does the filing disclose about an initial public offering?" />
      <div className="flex flex-wrap items-end gap-3"><label className="text-sm font-medium">Search method<select value={arm} onChange={(event) => { const next = event.target.value; if (next === 'B0' || next === 'B1' || next === 'B2' || next === 'B3') setArm(next) }} className="mt-2 block min-h-11 max-w-full rounded-lg border border-line px-3"><option value="B3">Hybrid + related disclosures</option><option value="B2">Hybrid text search</option><option value="B1">Filtered semantic search</option><option value="B0">Semantic baseline</option></select></label><Button type="submit" disabled={busy}>{busy ? 'Checking evidence…' : 'Find cited evidence'}</Button></div>
      {arm === 'B0' && <p className="text-xs text-muted">The baseline omits company, period and basis filters. Published corpus and active/history limits still apply.</p>}
    </form>
    {answer && <div aria-live="polite" className="mt-5">
      <p className="text-sm leading-6">{answer.explanation}</p>
      {answer.claims.length > 0 ? <ul className="mt-4 space-y-5">{answer.claims.map((claim) => <li key={claim.observation_id} className="border-l-2 border-sage pl-4"><p className="text-xs font-semibold text-muted">{answer.state === 'NUMERIC_VALUE' ? 'Accepted value and source' : 'Verbatim source excerpt'}</p><blockquote className="mt-2 whitespace-pre-wrap text-sm leading-7">{claim.text}</blockquote><FinancialContext quantity={claim.quantity ?? null} /><div className="mt-3 flex flex-wrap gap-2">{claim.citations.map((citation, index) => <Button key={`${citation.role}:${citation.span.evidence_id}:${citation.span.start}:${index}`} variant="secondary" disabled={busy} onClick={() => inspect(claim.observation_id, citation.span.evidence_id)}>Source {index + 1} · page {citation.page_index + 1}</Button>)}</div></li>)}</ul> : <p role="status" className="mt-3 text-sm font-semibold">No supported answer is available for this request.</p>}
      <details className="mt-4 break-all text-xs leading-6 text-muted"><summary className="cursor-pointer">Retrieval details</summary><p>Corpus {answer.retrieval.view.corpus_version_id}</p><p>Method {answer.retrieval.trace.arm} · {answer.retrieval.trace.context_tokens}/{answer.retrieval.trace.context_budget} context tokens · {answer.retrieval.trace.budget_omitted} complete bundles omitted by the budget.</p><p>Source excerpts only · no generated conclusion · paid provider calls {answer.retrieval.trace.provider_calls}.</p></details>
    </div>}
  </section>
}
