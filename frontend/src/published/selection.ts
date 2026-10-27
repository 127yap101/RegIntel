/** Page-session selection only: credentials and source/account data stay separate. */
export interface CorpusSelectionProps {
  selectedCorpus?: string | null
  onSelectCorpus?: ((identity: string | null) => void) | undefined
}
