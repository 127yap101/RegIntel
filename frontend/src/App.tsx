import { useEffect, useState } from 'react'
import { fetchBackendHealth, HealthCheckError } from './api/health'
import type { BackendHealth } from './api/health'
import { Button } from './components/Button'
import { Card } from './components/Card'
import { Explorer } from './published/Explorer'
import { AdminWorkspace } from './admin/Workspace'

type HealthState =
  | { kind: 'checking' }
  | { kind: 'available'; health: BackendHealth }
  | { kind: 'unavailable'; message: string }

const modules = [
  { id: 'M1', title: 'Corporate Intelligence', plan: 'Source-linked corporate facts, relationships and filing history.' },
  { id: 'M2', title: 'Analysis & Comparison', plan: 'Company comparisons that preserve financial period and reporting basis.' },
  { id: 'M3', title: 'Financial Learning', plan: 'Reviewed definitions and contextual, source-linked explanations.' },
  { id: 'M4', title: 'Virtual Portfolio', plan: 'A deterministic learning simulator with an immutable virtual ledger.' },
] as const

export default function App() {
  const [healthState, setHealthState] = useState<HealthState>({ kind: 'checking' })
  const [requestNumber, setRequestNumber] = useState(0)
  const [workspace, setWorkspace] = useState<'published' | 'admin'>('published')

  useEffect(() => {
    const controller = new AbortController()
    let current = true
    void fetchBackendHealth(controller.signal)
      .then((health) => {
        if (current) setHealthState({ kind: 'available', health })
      })
      .catch((error: unknown) => {
        if (!current) return
        setHealthState({
          kind: 'unavailable',
          message: error instanceof HealthCheckError ? error.message : 'The backend could not be reached. Please retry.',
        })
      })
    return () => {
      current = false
      controller.abort()
    }
  }, [requestNumber])

  function retryHealth(): void {
    setHealthState({ kind: 'checking' })
    setRequestNumber((previous) => previous + 1)
  }

  const statusTitle = healthState.kind === 'available'
    ? 'Backend available'
    : healthState.kind === 'unavailable'
      ? 'Backend unavailable'
      : 'Checking backend'

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <div className="mx-auto max-w-7xl px-5 sm:px-8 lg:px-12">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line py-6">
          <a href="#main-content" aria-label="RegIntel Finance home" className="flex items-center gap-3 rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sage">
            <span aria-hidden="true" className="flex h-11 w-11 items-center justify-center rounded-xl bg-ink text-sm font-bold tracking-tight text-white">RF</span>
            <span className="text-lg font-semibold tracking-tight text-ink">RegIntel <span className="font-normal text-muted">Finance</span></span>
          </a>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <a href="#project-status" className="rounded-md font-medium text-muted underline-offset-4 hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sage">Project status</a>
            <a href="#filing-explorer" onClick={() => setWorkspace('published')} className="rounded-full border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink">Explore published filings</a>
            <a href="#admin-workspace" onClick={() => setWorkspace('admin')} className="rounded-full border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink">Administrator workspace</a>
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="outline-none">
          <section aria-labelledby="welcome-heading" className="grid gap-8 py-12 sm:py-16 lg:grid-cols-[1.5fr_1fr] lg:items-end lg:gap-16">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-sage-dark">Evidence-grounded intelligence & learning</p>
              <h1 id="welcome-heading" className="mt-5 max-w-3xl text-4xl font-semibold leading-[1.12] tracking-[-0.045em] text-ink sm:text-5xl lg:text-6xl">From filings to<br />financial understanding.</h1>
              <p className="mt-6 max-w-xl text-base leading-7 text-muted sm:text-lg">RegIntel Finance is an academic capstone for source-linked corporate intelligence and financial learning.</p>
            </div>
            <aside aria-label="Current implementation scope" className="rounded-2xl bg-ink p-7 text-white sm:p-8">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sage-light">M1 · Published filing reads</p>
              <p className="mt-4 text-2xl font-medium leading-8 tracking-tight">Inspect a disclosure at its source.</p>
              <p className="mt-3 text-sm leading-6 text-white/80">Sign in to read published disclosures, directed corporate relations and exact source pages. Available content depends on the reviewed corpus on this machine.</p>
            </aside>
          </section>

          <div id="project-status" className="grid scroll-mt-6 gap-6 lg:grid-cols-[1.1fr_1fr]">
            <Card title="Backend connection" description="A liveness check for the local API, independent of business-module readiness.">
              <div role="status" aria-live="polite" aria-atomic="true" className="min-h-28">
                <div className="flex items-center gap-3">
                  <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${healthState.kind === 'available' ? 'bg-sage' : healthState.kind === 'unavailable' ? 'bg-amber' : 'bg-muted'}`} />
                  <p className="font-semibold text-ink">{statusTitle}</p>
                </div>
                <p className="mt-3 max-w-lg text-sm leading-6 text-muted">
                  {healthState.kind === 'available'
                    ? `Connected to the ${healthState.health.environment} API. This confirms liveness only; published data is loaded separately after sign-in.`
                    : healthState.kind === 'unavailable'
                      ? healthState.message
                      : 'Waiting for the backend health response. No company data is requested.'}
                </p>
              </div>
              <Button variant="secondary" disabled={healthState.kind === 'checking'} onClick={retryHealth} className="mt-3">
                {healthState.kind === 'checking' ? 'Checking…' : 'Check backend'}
              </Button>
            </Card>

            <Card title="Built around evidence" description="The planned platform follows these principles. They are design commitments, not measured outcomes.">
              <ul className="space-y-5">
                <li className="flex gap-3"><span aria-hidden="true" className="principle-number">01</span><div><p className="text-sm font-semibold text-ink">Exact source support</p><p className="mt-1 text-sm leading-6 text-muted">Accepted facts must trace to filing evidence and financial context.</p></div></li>
                <li className="flex gap-3"><span aria-hidden="true" className="principle-number">02</span><div><p className="text-sm font-semibold text-ink">History preserved</p><p className="mt-1 text-sm leading-6 text-muted">Amendments require explicit effects; later dates alone do not replace disclosures.</p></div></li>
                <li className="flex gap-3"><span aria-hidden="true" className="principle-number">03</span><div><p className="text-sm font-semibold text-ink">Deterministic finance</p><p className="mt-1 text-sm leading-6 text-muted">Financial calculations belong to validated application logic.</p></div></li>
              </ul>
            </Card>
          </div>

          <section aria-labelledby="modules-heading" className="py-12 sm:py-16">
            <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
              <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">Planned platform</p><h2 id="modules-heading" className="mt-2 text-2xl font-semibold tracking-tight text-ink">Four connected modules</h2></div>
              <p className="text-sm text-muted">M1 published reads available · M2–M4 planned</p>
            </div>
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {modules.map((module) => (
                <li key={module.id} className="rounded-xl border border-line bg-white p-6">
                  <div className="flex items-center justify-between gap-2"><span className="text-xs font-bold tracking-wider text-sage-dark">{module.id}</span><span className="rounded-full bg-paper px-2.5 py-1 text-[11px] font-medium text-muted">{module.id === 'M1' ? 'Published reads' : 'Not implemented'}</span></div>
                  <h3 className="mt-6 text-lg font-semibold tracking-tight text-ink">{module.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted">Planned: {module.plan}</p>
                </li>
              ))}
            </ul>
          </section>
          {workspace === 'published' ? <Explorer /> : <AdminWorkspace />}
        </main>

        <footer className="flex flex-wrap justify-between gap-3 border-t border-line py-6 text-xs leading-5 text-muted">
          <p>RegIntel Finance · Six-week academic capstone</p>
          <p>Information and learning · No investment recommendations</p>
        </footer>
      </div>
    </>
  )
}
