import { Button } from '../components/Button'
import type { LedgerPage } from './generated'

export function PortfolioHistory({ ledger, busy, companyName, onVersion, onPage }: { ledger: LedgerPage | null; busy: boolean; companyName: (identity: string) => string; onVersion: (version: string) => void; onPage: (offset: number) => void }) {
  return <section className="rounded-xl border border-line bg-white p-5">
    <h3 className="font-semibold">Immutable virtual history</h3>
    {ledger?.entries.length ? <ol className="mt-3 space-y-3 text-sm">{ledger.entries.map((entry) => <li key={entry.id} className="border-b border-line pb-3">
      #{entry.sequence} · {entry.request.side} {entry.request.quantity} {companyName(entry.request.company_id)} · {entry.evaluation.state} · {entry.evaluation.reason.replaceAll('_', ' ')}
      <span className="mt-1 block text-xs text-muted">Cash after outcome: INR {entry.evaluation.after.cash}</span>
      <Button variant="secondary" className="mt-2" disabled={busy} onClick={() => onVersion(entry.id)}>View balances after order #{entry.sequence}</Button>
    </li>)}</ol> : <p className="mt-3 text-sm text-muted">No virtual orders recorded.</p>}
    {ledger && <p className="mt-3 break-all text-xs text-muted">Selected portfolio version: {ledger.portfolio_version_id}</p>}
    <div className="mt-3 flex flex-wrap gap-3">
      {ledger && ledger.offset > 0 && <Button variant="secondary" disabled={busy} onClick={() => onPage(Math.max(0, ledger.offset - 50))}>Previous history page</Button>}
      {ledger && ledger.offset + ledger.entries.length < ledger.total && <Button variant="secondary" disabled={busy} onClick={() => onPage(ledger.offset + ledger.entries.length)}>Next history page</Button>}
    </div>
  </section>
}
