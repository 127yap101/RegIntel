import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { CompanyGraph } from './api'
import type { ReactNode } from 'react'
import type { PublishedObservation } from './generated'
import { FinancialContext } from './FinancialContext'

export function RelationGraph({ graph, select, support }: { graph: CompanyGraph; select: (observation: string) => void; support: (observation: PublishedObservation) => ReactNode }) {
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!container.current) return
    const instance = cytoscape({ container: container.current,
      elements: [...graph.nodes.map((node) => ({ data: { id: node.id, name: node.name } })), ...graph.edges.map((edge) => ({ data: { id: edge.id, source: edge.subject_entity_id, target: edge.object_entity_id, name: edge.relation_type } }))],
      style: [{ selector: 'node', style: { label: 'data(name)', 'background-color': '#387d66', 'font-size': 11, 'text-wrap': 'wrap', 'text-max-width': '140px' } }, { selector: 'edge', style: { label: 'data(name)', 'curve-style': 'bezier', 'target-arrow-shape': 'triangle', width: 2, 'font-size': 10 } }],
      layout: { name: 'circle', animate: false, padding: 50 }, minZoom: 0.5, maxZoom: 2,
    })
    instance.edges().forEach((edge) => { edge.on('tap', () => select(edge.id())) })
    const observer = new ResizeObserver(() => { instance.resize(); instance.fit(undefined, 35) })
    observer.observe(container.current)
    return () => { observer.disconnect(); instance.destroy() }
  }, [graph, select])
  const names = new Map(graph.nodes.map((node) => [node.id, node.name]))
  return <section aria-label="Published corporate relations" className="mt-6 rounded-xl border border-line bg-white p-5"><h3 className="text-lg font-semibold">Corporate relations</h3><div ref={container} aria-hidden="true" className="relative mt-3 h-56 w-full overflow-hidden" />{graph.edges.length === 0 ? <p className="text-sm text-muted">No corporate relations are published in this view.</p> : <ul className="space-y-5">{graph.edges.map((edge) => <li key={edge.id}><button className="text-left text-sm underline underline-offset-4" onClick={() => select(edge.id)}>{names.get(edge.subject_entity_id)} → {edge.relation_type} → {edge.object_entity_id ? names.get(edge.object_entity_id) : ''} · inspect support</button><blockquote className="mt-3 whitespace-pre-wrap text-sm leading-6">{edge.raw_text}</blockquote><FinancialContext quantity={edge.quantity} />{support(edge)}</li>)}</ul>}</section>
}
