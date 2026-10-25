import { useEffect, useState } from 'react'
import { Button } from '../components/Button'
import { ModuleApi } from './api'
import type { DefinitionDraft, LearningStarterPack } from './generated'

export function StarterDrafts({ api, busy, onUse }: { api: ModuleApi; busy: boolean; onUse: (draft: DefinitionDraft) => void }) {
  const [pack, setPack] = useState<LearningStarterPack | null>(null)
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void api.read('starter_pack', '/v1/learning/starter-pack', controller.signal).then((value) => {
      if (!controller.signal.aborted) { setPack(value); setError('') }
    }).catch((failure: unknown) => { if (!controller.signal.aborted) { setPack(null); setError(failure instanceof Error ? failure.message : 'Starter drafts are unavailable.') } })
    return () => controller.abort()
  }, [api])
  const draft = pack?.drafts.find((item) => item.key === selected)?.draft
  return <section className="rounded-lg border border-line bg-white p-4" aria-labelledby="starter-drafts-heading">
    <h4 id="starter-drafts-heading" className="font-semibold">Unreviewed learning starters</h4>
    <p className="mt-2 text-sm text-muted">Load a draft for editing, then inspect its sources and example. Loading does not save, approve or publish it.</p>
    {pack && <>
      <p className="mt-2 text-xs text-muted">{pack.applicability}</p>
      <label className="mt-4 block text-sm">Unreviewed starter term<select className="mt-1 min-h-11 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm" value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Select a draft</option>{pack.drafts.map((item) => <option key={item.key} value={item.key}>{item.draft.term}</option>)}</select></label>
      <Button className="mt-3" variant="secondary" disabled={busy || !draft} onClick={() => { if (draft) onUse(draft) }}>Load starter for editing</Button>
      <p className="mt-3 text-xs text-muted">Prepared as a draft · sources checked {pack.source_checked_on} · explicit content review pending</p>
    </>}
    {!pack && !error && <p role="status" className="mt-3 text-sm">Loading unreviewed starters…</p>}
    {error && <p role="status" className="mt-3 text-sm">{error}</p>}
  </section>
}
