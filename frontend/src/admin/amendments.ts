import { sameValue } from '../contracts/equality'
import type * as T from './generated'

type Support = T.LineageProposal['parent_identity']

export function amendmentSpans(value: Support): readonly T.SourceSpan[] { return 'spans' in value ? value.spans : [value] }

export function checkAmendmentSupport(value: Support, parse?: string): void {
  const spans = amendmentSpans(value)
  if (spans.some((span) => [...span.quote].length !== span.end - span.start)) throw new Error('Amendment source span differs')
  if ('spans' in value && (value.schema_version !== 'native-amendment-words-1' || parse !== undefined && value.parse_version_id !== parse || spans.length < 1 || spans.length > 128 || new Set(spans.map((span) => span.evidence_id)).size !== spans.length || spans.some((span) => span.start !== 0) || spans.reduce((length, span) => length + [...span.quote].length, 0) > 20_000)) throw new Error('Native amendment proof differs')
}

export function amendmentContains(whole: Support, part: Support): boolean {
  if ('spans' in part) return 'spans' in whole && whole.parse_version_id === part.parse_version_id && whole.spans.some((_, start) => sameValue(whole.spans.slice(start, start + part.spans.length), part.spans))
  return amendmentSpans(whole).some((span) => span.evidence_id === part.evidence_id && span.start <= part.start && part.end <= span.end)
}

export function checkManifestAmendments(manifest: T.CorpusManifest): void {
  for (const { proposal } of manifest.lineages) {
    const parent = manifest.filings.find((filing) => filing.filing_version_id === proposal.parent_filing_version_id)
    const child = manifest.filings.find((filing) => filing.filing_version_id === proposal.child_filing_version_id)
    if (!parent || !child || parent.filing_id === child.filing_id) throw new Error('Amendment filing scope differs')
    checkAmendmentSupport(proposal.parent_identity, parent.parse_version_id)
    checkAmendmentSupport(proposal.child_identity, child.parse_version_id)
    checkAmendmentSupport(proposal.parent_reference, child.parse_version_id)
  }
  for (const { proposal } of manifest.effects) {
    const lineage = manifest.lineages.find((lineage) => lineage.proposal.id === proposal.lineage_id)
    const child = manifest.filings.find((filing) => filing.filing_version_id === lineage?.proposal.child_filing_version_id)
    if (!child) throw new Error('Effect lineage is unavailable')
    for (const support of proposal.supports) checkAmendmentSupport(support, child.parse_version_id)
    if (proposal.effective_date_support) {
      checkAmendmentSupport(proposal.effective_date_support, child.parse_version_id)
      if (!proposal.supports.some((support) => amendmentContains(support, proposal.effective_date_support!))) throw new Error('Effect date is outside its exact statement')
    }
  }
}
