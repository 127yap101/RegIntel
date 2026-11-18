import { useEffect, useState } from 'react'
import { Link, useLocation } from 'wouter'
import { fetchBackendHealth, HealthCheckError } from './api/health'
import type { BackendHealth } from './api/health'
import { Button } from './components/Button'
import { Card } from './components/Card'
import { Explorer } from './published/Explorer'
import { AdminWorkspace } from './admin/Workspace'
import { ModuleWorkspace } from './modules/Workspace'
import { AppLayout } from './layouts/AppLayout'
import { LandingPage } from './pages/LandingPage'

type HealthState =
  | { kind: 'checking' }
  | { kind: 'available'; health: BackendHealth }
  | { kind: 'unavailable'; message: string }

type Workspace = 'published' | 'admin' | 'learning' | 'portfolio'
type Page = { title: string; workspace?: Workspace; home?: boolean; status?: boolean }

function selectedPage(path: string): Page | null {
  if (path === '/') return { title: 'Platform overview', workspace: 'published', home: true }
  if (path === '/app') return { title: 'Corporate intelligence', workspace: 'published' }
  if (path === '/app/companies') return { title: 'Company directory', workspace: 'published' }
  if (path === '/app/research') return { title: 'Research & evidence', workspace: 'published' }
  if (path === '/app/comparison') return { title: 'Analysis & comparison', workspace: 'published' }
  if (path === '/app/learning') return { title: 'Learning workspace', workspace: 'learning' }
  if (path === '/app/portfolio') return { title: 'Portfolio workspace', workspace: 'portfolio' }
  if (path === '/app/status') return { title: 'System status', status: true }
  if (['/admin', '/admin/filings', '/admin/processing', '/admin/reviews', '/admin/publications'].includes(path)) return { title: 'Operations console', workspace: 'admin' }
  return null
}

export default function App() {
  const [location, navigate] = useLocation()
  const page = selectedPage(location)
  const [healthState, setHealthState] = useState<HealthState>({ kind: 'checking' })
  const [requestNumber, setRequestNumber] = useState(0)
  const [selectedCorpus, setSelectedCorpus] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void fetchBackendHealth(controller.signal)
      .then((health) => { if (!controller.signal.aborted) setHealthState({ kind: 'available', health }) })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setHealthState({ kind: 'unavailable', message: error instanceof HealthCheckError ? error.message : 'The backend could not be reached. Please retry.' })
      })
    return () => controller.abort()
  }, [requestNumber])

  const statusTitle = healthState.kind === 'available' ? 'Backend available' : healthState.kind === 'unavailable' ? 'Backend unavailable' : 'Checking backend'
  const connection = <Card title="Backend connection" description="A liveness check for the local API, independent of business-module readiness.">
    <div role="status" aria-live="polite" aria-atomic="true" className="min-h-28">
      <div className="flex items-center gap-3">
        <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${healthState.kind === 'available' ? 'bg-sage' : healthState.kind === 'unavailable' ? 'bg-amber' : 'bg-muted'}`} />
        <p className="font-semibold text-ink">{statusTitle}</p>
      </div>
      <p className="mt-3 max-w-lg text-sm leading-6 text-muted">{healthState.kind === 'available'
        ? `Connected to the ${healthState.health.environment} API. This confirms liveness only; published data is loaded separately after sign-in.`
        : healthState.kind === 'unavailable' ? healthState.message : 'Waiting for the backend health response. No company data is requested.'}</p>
    </div>
    <Button variant="secondary" disabled={healthState.kind === 'checking'} onClick={() => { setHealthState({ kind: 'checking' }); setRequestNumber((previous) => previous + 1) }} className="mt-3">{healthState.kind === 'checking' ? 'Checking…' : 'Check backend'}</Button>
  </Card>

  return <AppLayout location={location} title={page?.title ?? 'Page not found'}>
    {page?.home && <LandingPage connection={connection} onChooseWorkspace={(_workspace, path) => navigate(path)} />}
    {!page?.home && <div className="mb-8"><p className="text-xs font-semibold uppercase tracking-[0.16em] text-sage-dark">RegIntel Finance</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">{page?.title ?? 'Page not found'}</h1></div>}
    {page?.status && <div className="max-w-3xl space-y-6">{connection}<Card title="Content readiness" description="A running API and reviewed content are separate checks."><p className="text-sm leading-6 text-muted">Published filings, reviewed learning and portfolio records are loaded after sign-in in their respective workspaces. Quote availability is reported by the application; this page does not infer it from the connection check.</p></Card></div>}
    {page?.workspace === 'published' ? <Explorer selectedCorpus={selectedCorpus} onSelectCorpus={setSelectedCorpus} /> : page?.workspace === 'admin' ? <AdminWorkspace /> : page?.workspace ? <ModuleWorkspace mode={page.workspace} selectedCorpus={selectedCorpus} onSelectCorpus={setSelectedCorpus} /> : null}
    {!page && <div className="rounded-xl border border-line bg-white p-6"><p className="text-sm text-muted">This page is not available. Choose a workspace from the navigation or return to the platform overview.</p><Link href="/" className="mt-4 inline-flex font-semibold text-sage-dark underline underline-offset-4">Return to overview</Link></div>}
  </AppLayout>
}
