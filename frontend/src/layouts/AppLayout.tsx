import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'wouter'
import { Activity, BookOpen, Building2, ChevronRight, Home, Menu, PieChart, Search, ShieldCheck, TrendingUp, X } from 'lucide-react'

const navigation = [
  { href: '/', label: 'Platform overview', icon: Home, group: 'Overview' },
  { href: '/app/companies', label: 'Explore published filings', icon: Building2, group: 'M1 · Corporate intelligence' },
  { href: '/app/research', label: 'Research & evidence', icon: Search, group: 'M1 · Corporate intelligence' },
  { href: '/app/comparison', label: 'Analysis & comparison', icon: TrendingUp, group: 'M2 · Analysis' },
  { href: '/app/learning', label: 'Financial learning', icon: BookOpen, group: 'M3 · Learning' },
  { href: '/app/portfolio', label: 'Virtual portfolio', icon: PieChart, group: 'M4 · Practice' },
  { href: '/admin', label: 'Administrator workspace', icon: ShieldCheck, group: 'Operations' },
  { href: '/app/status', label: 'Project status', icon: Activity, group: 'Operations' },
] as const

function Navigation({ location, onNavigate }: { location: string; onNavigate?: () => void }) {
  return <nav aria-label="Primary navigation" className="space-y-1">
    {navigation.map((item, index) => {
      const Icon = item.icon
      const active = location === item.href || item.href === '/admin' && location.startsWith('/admin/') || item.href === '/app/companies' && location === '/app'
      return <div key={item.href}>
        {item.group !== navigation[index - 1]?.group && <p className="px-3 pt-5 pb-2 text-[10px] font-semibold uppercase tracking-[0.13em] text-muted">{item.group}</p>}
        <Link href={item.href} onClick={onNavigate} aria-current={active ? 'page' : undefined} className={`flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${active ? 'bg-sage-light text-sage-dark' : 'text-muted hover:bg-paper hover:text-ink'}`}><Icon aria-hidden="true" className="h-4 w-4 shrink-0" /><span>{item.label}</span></Link>
      </div>
    })}
  </nav>
}

function Brand() {
  return <Link href="/" aria-label="RegIntel Finance home" className="flex items-center gap-3 rounded-md">
    <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-ink text-xs font-bold tracking-tight text-white">RF</span>
    <span><span className="block text-sm font-bold tracking-tight text-ink">RegIntel Finance</span><span className="block text-[11px] text-muted">Evidence to understanding</span></span>
  </Link>
}

function MobileNavigation({ location, onClose }: { location: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const selected = dialog.current
    selected?.showModal()
    closeButton.current?.focus()
    return () => { selected?.close() }
  }, [])
  function dismiss() {
    // Release the modal's inert background before restoring focus to its opener.
    dialog.current?.close()
    onClose()
  }
  return <dialog ref={dialog} aria-label="Workspace navigation" className="m-0 h-dvh max-h-none w-80 max-w-[calc(100%_-_2rem)] border-0 bg-white p-0 text-ink shadow-xl backdrop:bg-ink/40" onCancel={(event) => { event.preventDefault(); dismiss() }}>
    <div className="flex items-center justify-between border-b border-line p-4"><span className="text-sm font-semibold">Choose a workspace</span><button ref={closeButton} type="button" onClick={dismiss} aria-label="Close navigation" className="flex h-11 w-11 items-center justify-center rounded-md text-muted hover:bg-paper"><X aria-hidden="true" className="h-5 w-5" /></button></div>
    <div className="max-h-[calc(100dvh-5rem)] overflow-y-auto px-3 pb-5"><Navigation location={location} onNavigate={dismiss} /></div>
  </dialog>
}

export function AppLayout({ children, location, title }: { children: ReactNode; location: string; title: string }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  function closeMenu() { setMenuOpen(false); menuButton.current?.focus() }
  return <div className="min-h-screen bg-paper text-ink">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <div className="flex min-h-screen">
      <aside aria-label="Workspace sidebar" className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-line bg-white md:flex">
        <div className="border-b border-line px-5 py-5"><Brand /></div>
        <div className="flex-1 overflow-y-auto px-3 pb-5"><Navigation location={location} /></div>
        <div className="space-y-2 border-t border-line bg-paper/50 p-5 text-[11px] leading-5 text-muted"><p className="font-semibold text-ink">Academic pilot</p><p>Information and learning.<br />No investment recommendations.</p></div>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex min-h-16 items-center justify-between gap-4 border-b border-line bg-white/95 px-5 py-3 backdrop-blur-sm sm:px-8">
          <div className="md:hidden"><Brand /></div>
          <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-2 text-xs md:flex"><Link href="/" className="shrink-0 text-muted hover:text-ink">Platform</Link><ChevronRight aria-hidden="true" className="h-3 w-3 shrink-0 text-muted" /><span aria-current="page" className="truncate font-medium">{title}</span></nav>
          <span className="hidden text-[11px] text-muted md:block">Source-linked intelligence & learning</span>
          <button ref={menuButton} type="button" onClick={() => setMenuOpen(true)} aria-label="Open navigation" aria-haspopup="dialog" aria-expanded={menuOpen} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-line text-muted hover:bg-paper md:hidden"><Menu aria-hidden="true" className="h-5 w-5" /></button>
        </header>
        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-7xl px-5 py-8 outline-none sm:px-8 lg:px-10">{children}</main>
        <footer className="mx-5 flex flex-wrap justify-between gap-3 border-t border-line py-6 text-xs leading-5 text-muted sm:mx-8 lg:mx-10"><p>RegIntel Finance · Academic capstone</p><p>Published content depends on completed source review.</p></footer>
      </div>
    </div>
    {menuOpen && <MobileNavigation location={location} onClose={closeMenu} />}
  </div>
}
