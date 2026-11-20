import { useState } from 'react'
import { Button } from '../components/Button'
import { AdminApi } from './api'
import { numericalRefreshRequest } from './numericalRefresh'
import type * as T from './generated'

interface Props {
  api: AdminApi
  packet: T.NumericalReviewPacket
  busy: boolean
  locked: boolean
  run: (action: (signal: AbortSignal) => Promise<void>) => Promise<void>
  pendingChanged: (pending: boolean) => void
  openRefreshed: (result: T.NumericalRefreshResult) => void
}

export function NumericalRefreshPanel({ api, packet, busy, locked, run, pendingChanged, openRefreshed }: Props) {
  const [pending, setPending] = useState<T.NumericalRefreshRequest | null>(null)
  function refresh(): void {
    if (busy || locked && !pending) return
    void run(async (signal) => {
      const body = pending ?? await numericalRefreshRequest(packet)
      if (signal.aborted) return
      setPending(body); pendingChanged(true)
      // An uncertain response must retain the exact original selection. A later
      // attempt checks current approvals again; it never approves financial data.
      const result = await api.refreshNumerical(packet, body, signal)
      if (!signal.aborted) { setPending(null); pendingChanged(false); openRefreshed(result) }
    })
  }
  return <section aria-label="Refresh numerical prerequisites" className="mt-4 rounded border border-line p-3">
    <h4 className="text-sm font-semibold">Refresh source and approval checks</h4>
    <p className="mt-2 text-sm text-muted">After prerequisite registrations are reviewed, rerun the machine checks with the current approvals. The exact source selection and previous records remain available. Applicability review, context confirmation, acceptance and publication are separate actions.</p>
    {pending && <p role="status" className="mt-2 text-sm">The refresh has no verified response yet. Keep this gate selected and retry the same request.</p>}
    <Button className="mt-3" variant="secondary" disabled={busy || locked && !pending} onClick={refresh}>{pending ? 'Retry the same source refresh' : 'Refresh source and approval checks'}</Button>
  </section>
}
