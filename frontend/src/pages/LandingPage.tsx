import type { MouseEvent, ReactNode } from 'react'

type Workspace = 'published' | 'admin' | 'learning' | 'portfolio'

const destinations: Record<Workspace, string> = {
  published: '/app/companies',
  admin: '/admin',
  learning: '/app/learning',
  portfolio: '/app/portfolio',
}

const modules: readonly { id: string; title: string; description: string; context: string; action: string; status: string; workspace: Workspace; path?: string }[] = [
  {
    id: 'M1', title: 'Corporate Intelligence', workspace: 'published', action: 'Explore filing evidence', status: 'Published reads',
    description: 'Read published corporate disclosures, relationships and filing history, then inspect the original source page.',
    context: 'Available disclosures depend on the reviewed, published corpus.',
  },
  {
    id: 'M2', title: 'Analysis & Comparison', workspace: 'published', action: 'Open company comparisons', status: 'Published comparison', path: '/app/comparison',
    description: 'Compare published financial inputs with their periods, units, reporting basis and supporting evidence.',
    context: 'Missing or incompatible inputs are shown explicitly.',
  },
  {
    id: 'M3', title: 'Financial Learning', workspace: 'learning', action: 'Open financial learning', status: 'Reviewed learning',
    description: 'Explore reviewed definitions and educational examples, with links to their sources and published filing context.',
    context: 'Draft definitions remain private until reviewed and published.',
  },
  {
    id: 'M4', title: 'Virtual Portfolio', workspace: 'portfolio', action: 'Open virtual portfolio', status: 'Virtual ledger',
    description: 'Practice with a virtual account, inspect immutable order history and trace portfolio calculations to their inputs.',
    context: 'Quotes are currently unavailable. No real money is used.',
  },
]

function Arrow() {
  return <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="h-4 w-4 shrink-0"><path d="M4 10h12m-5-5 5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

export function LandingPage({ connection, onChooseWorkspace }: { connection: ReactNode; onChooseWorkspace: (workspace: Workspace, path: string) => void }) {
  function choose(event: MouseEvent<HTMLAnchorElement>, workspace: Workspace, path = destinations[workspace]): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.defaultPrevented) return
    event.preventDefault()
    onChooseWorkspace(workspace, path)
  }
  return <div className="space-y-10 sm:space-y-14">
    <section aria-labelledby="welcome-heading" className="grid gap-8 border-b border-line pb-10 pt-4 lg:grid-cols-[1.4fr_1fr] lg:items-center lg:gap-14">
      <div>
        <p className="inline-flex rounded-full border border-line bg-white px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-sage-dark">Evidence-grounded intelligence &amp; learning</p>
        <h1 id="welcome-heading" className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.12] tracking-[-0.045em] text-ink sm:text-5xl lg:text-6xl">From filings to<br />financial understanding.</h1>
        <p className="mt-5 max-w-xl text-base leading-7 text-muted">Explore source-linked corporate disclosures, compare compatible financial figures and learn with a virtual portfolio. RegIntel Finance is an academic capstone.</p>
        <div className="mt-7 flex flex-wrap gap-3">
          <a href={destinations.published} onClick={(event) => choose(event, 'published')} className="inline-flex min-h-11 items-center gap-3 rounded-lg bg-ink px-5 py-2.5 text-sm font-semibold text-white hover:bg-ink-soft focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sage">Start with published filings<Arrow /></a>
          <a href={destinations.admin} onClick={(event) => choose(event, 'admin')} className="inline-flex min-h-11 items-center gap-3 rounded-lg border border-line bg-white px-4 py-2.5 text-sm font-semibold text-ink hover:bg-paper focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sage">Open review workspace<Arrow /></a>
        </div>
      </div>
      <aside aria-label="Following the evidence" className="rounded-2xl bg-ink p-7 text-white sm:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sage-light">From disclosure to source</p>
        <h2 className="mt-4 text-2xl font-medium leading-8 tracking-tight">Keep the context in view.</h2>
        <ol className="mt-6 space-y-5">
          {[
            ['Choose a published view', 'Select a filing corpus and company before exploring its disclosures.'],
            ['Inspect the exact evidence', 'Open the original source page and retain the disclosure’s conditions.'],
            ['Check the financial context', 'Compare figures only when their periods, units and reporting basis are compatible.'],
          ].map(([title, detail], index) => <li key={title} className="flex gap-3"><span aria-hidden="true" className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-white/25 text-xs text-sage-light">{index + 1}</span><div><p className="text-sm font-semibold">{title}</p><p className="mt-1 text-sm leading-6 text-white/70">{detail}</p></div></li>)}
        </ol>
      </aside>
    </section>

    <section aria-labelledby="modules-heading">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">Choose a workspace</p><h2 id="modules-heading" className="mt-2 text-2xl font-semibold tracking-tight text-ink">Four connected modules</h2></div>
        <p className="max-w-md text-sm leading-6 text-muted">Sign in to inspect the content available in this installation.</p>
      </div>
      <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {modules.map((module) => <li key={module.id} className="flex flex-col rounded-xl border border-line bg-white p-5 shadow-xs">
          <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-bold tracking-wider text-sage-dark">{module.id}</span><span className="rounded-full bg-paper px-2.5 py-1 text-[11px] font-medium text-muted">{module.status}</span></div>
          <h3 className="mt-4 text-lg font-semibold tracking-tight text-ink">{module.title}</h3>
          <p className="mt-3 text-sm leading-6 text-muted">{module.description}</p>
          <p className="mt-4 border-t border-line pt-4 text-xs leading-5 text-muted">{module.context}</p>
          <a href={module.path ?? destinations[module.workspace]} onClick={(event) => choose(event, module.workspace, module.path)} className="mt-auto flex min-h-11 items-center justify-between gap-2 rounded pt-5 text-sm font-semibold text-sage-dark underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sage">{module.action}<Arrow /></a>
        </li>)}
      </ul>
    </section>

    <section id="project-status" aria-labelledby="readiness-heading" className="grid scroll-mt-20 gap-6 lg:grid-cols-2">
      {connection}
      <div className="rounded-xl border border-line bg-white p-6 sm:p-7">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">Before testing</p>
        <h2 id="readiness-heading" className="mt-3 text-xl font-semibold tracking-tight">Connection and content are separate.</h2>
        <p className="mt-3 text-sm leading-6 text-muted">A running API does not establish that filings or learning definitions have been approved. Each workspace shows its available published content and any missing inputs.</p>
        <p className="mt-3 text-sm leading-6 text-muted">Use this installation’s local account. A fresh clone starts without another person’s credentials, source PDFs or published corpus.</p>
      </div>
    </section>
  </div>
}
