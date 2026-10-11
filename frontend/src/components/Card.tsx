import { useId } from 'react'
import type { ReactNode } from 'react'

interface CardProps {
  title: string
  description?: string
  children: ReactNode
  className?: string
}

export function Card({ title, description, children, className = '' }: CardProps) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className={`rounded-2xl border border-line bg-white p-6 sm:p-8 ${className}`}>
      <h2 id={headingId} className="text-xl font-semibold tracking-tight text-ink">{title}</h2>
      {description && <p className="mt-2 text-sm leading-6 text-muted">{description}</p>}
      <div className="mt-6">{children}</div>
    </section>
  )
}
