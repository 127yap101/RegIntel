import { useId, useState } from 'react'
import { Button } from '../components/Button'
import type * as T from './generated'

export function UploadForm({ busy, upload }: { busy: boolean; upload: (file: File, metadata: unknown) => void }) {
  const docTypeId = useId()
  const [file, setFile] = useState<File | null>(null)
  const [company, setCompany] = useState('')
  const [kind, setKind] = useState<T.UploadMetadata['document_type']>('RHP')
  const [url, setUrl] = useState(''); const [date, setDate] = useState(''); const [parent, setParent] = useState('')
  return <details className="mt-5 rounded-xl border border-line bg-white p-4"><summary className="cursor-pointer font-semibold">Upload a filing</summary><form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); if (file) upload(file, { company_name_raw: company, document_type: kind, source_url: url || null, published_on: date || null, declared_parent_filing_version_id: parent || null }) }}>
    <label className="text-sm font-medium sm:col-span-2">Original PDF (up to 64 MiB)<input type="file" required accept="application/pdf,.pdf" disabled={busy} onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="mt-2 block max-w-full text-sm" /></label>
    <label className="text-sm font-medium">Company name as disclosed<input required maxLength={256} value={company} onChange={(event) => setCompany(event.target.value)} className="admin-input" /></label>
    <div><label htmlFor={docTypeId} className="text-sm font-medium">Filing type</label><select id={docTypeId} value={kind} onChange={(event) => { const next = event.target.value; if (next === 'RHP' || next === 'DRHP' || next === 'PROSPECTUS' || next === 'ADDENDUM' || next === 'CORRIGENDUM') setKind(next) }} className="admin-input"><option>RHP</option><option>DRHP</option><option>PROSPECTUS</option><option>ADDENDUM</option><option>CORRIGENDUM</option></select></div>
    <label className="text-sm font-medium sm:col-span-2">Original public source URL (optional)<input type="url" value={url} onChange={(event) => setUrl(event.target.value)} className="admin-input" /></label>
    <label className="text-sm font-medium">Source publication date (only if known)<input type="date" value={date} onChange={(event) => setDate(event.target.value)} className="admin-input" /></label>
    <label className="text-sm font-medium">Declared parent filing version (optional)<input value={parent} onChange={(event) => setParent(event.target.value)} className="admin-input" /></label>
    <p className="text-xs leading-6 text-muted sm:col-span-2">Leave unsupported dates and parent references empty. The source is hashed and deduplicated; a declared parent still requires evidence-backed lineage review.</p>
    <Button type="submit" disabled={busy || !file}>Submit PDF for parsing</Button>
  </form></details>
}

export function FilingPanel({ job, metrics, busy, refresh, start }: { job: T.FilingJob; metrics: readonly T.MetricDefinition[] | null; busy: boolean; refresh: () => void; start: (ids: readonly T.MetricDefinition['id'][]) => void }) {
  const [selected, setSelected] = useState<readonly T.MetricDefinition['id'][]>([])
  return <section className="mt-5 rounded-xl border border-line bg-white p-5" aria-label="Filing job details"><h3 className="font-semibold">Filing state: {job.state}</h3><dl className="mt-3 space-y-2 break-all text-xs text-muted"><div><dt>Job</dt><dd>{job.id}</dd></div><div><dt>Original source SHA256</dt><dd>{job.source_sha256}</dd></div><div><dt>Filing / parse version</dt><dd>{job.filing_version_id} / {job.parse_version_id ?? 'Not parsed'}</dd></div></dl><p className="mt-3 text-sm">Attempts {job.attempts} · source pages {job.page_count ?? 'Unavailable'}{job.failure_code ? ` · ${job.failure_code}` : ''}</p><Button className="mt-3" variant="secondary" disabled={busy} onClick={refresh}>Refresh filing state</Button>
    {job.state === 'PARSED' && <form className="mt-5 space-y-3" onSubmit={(event) => { event.preventDefault(); start(selected) }}><fieldset><legend className="text-sm font-semibold">Reviewed extraction metrics</legend>{metrics?.length ? <div className="mt-3 space-y-2">{metrics.map((metric) => <label key={metric.id} className="flex items-center gap-3 text-sm"><input type="checkbox" checked={selected.includes(metric.id)} disabled={busy} onChange={(event) => setSelected(event.target.checked ? [...selected, metric.id] : selected.filter((id) => id !== metric.id))} />{metric.label}</label>)}</div> : <p className="mt-2 text-sm text-muted">{metrics === null ? 'The extraction metric catalog has not been loaded. Refresh the filing state to load it.' : 'No registered extraction metrics are available. Fact extraction needs explicitly reviewed metric definitions.'}</p>}</fieldset><Button type="submit" disabled={busy || !selected.length}>Start extraction and validation</Button></form>}
  </section>
}

export function ProcessingPanel({ job, busy, refresh, dispatch, review, validate }: { job: T.ProcessingJob; busy: boolean; refresh: () => void; dispatch: () => void; review: (id: string) => void; validate: (id: string) => void }) {
  const validation = job.checkpoints.find((item) => item.stage === 'VALIDATION')
  const candidates = job.checkpoints.find((item) => item.stage === 'CANDIDATE')
  return <section aria-label="Processing job details" className="mt-5 rounded-xl border border-line bg-white p-5"><h3 className="font-semibold">Processing state: {job.state}</h3><p className="mt-3 break-all text-xs text-muted">Job {job.id} · generation {job.generation}{job.failure_code ? ` · ${job.failure_code}` : ''}</p><ul className="mt-3 space-y-2">{job.checkpoints.map((item) => <li key={item.stage} className="break-all text-xs">{item.stage}: {item.output_id}</li>)}</ul><div className="mt-4 flex flex-wrap gap-3"><Button variant="secondary" disabled={busy} onClick={refresh}>Refresh workflow</Button><Button variant="secondary" disabled={busy || !['QUEUED', 'RUNNING'].includes(job.state)} onClick={dispatch}>Dispatch pending workflow</Button>{validation && <Button disabled={busy} onClick={() => review(validation.output_id)}>Review validated candidates</Button>}{candidates && <Button variant="secondary" disabled={busy} onClick={() => validate(candidates.output_id)}>Run current validation</Button>}</div><details className="mt-4"><summary className="cursor-pointer text-sm">Immutable workflow events</summary><ol className="mt-3 space-y-2">{job.events.map((event) => <li key={event.sequence} className="text-xs">{event.sequence}. {event.kind} · generation {event.generation}{event.stage ? ` · ${event.stage}` : ''}{event.failure_code ? ` · ${event.failure_code}` : ''}</li>)}</ol></details></section>
}
