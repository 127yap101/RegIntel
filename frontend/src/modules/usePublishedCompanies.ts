import { useEffect, useRef, useState } from 'react'
import type { CompanyPage, PublishedApi } from '../published/api'

type Client = Pick<PublishedApi, 'current' | 'companies'>

export function usePublishedCompanies(client: Client, selectedCorpus: string | null, onSelectCorpus?: (identity: string | null) => void) {
  const [companies, setCompanies] = useState<CompanyPage | null>(null)
  const [error, setError] = useState('')
  const resolved = useRef<{ client: Client; corpus: string } | null>(null)
  useEffect(() => {
    if (selectedCorpus && resolved.current?.client === client && resolved.current.corpus === selectedCorpus) return
    const controller = new AbortController()
    resolved.current = null
    setCompanies(null); setError('')
    void (async () => {
      // Let cleanup cancel a replaced effect before starting its first request.
      // This also avoids two head reads during React's development effect probe.
      await Promise.resolve()
      if (controller.signal.aborted) return
      const corpus = selectedCorpus ?? (await client.current(controller.signal)).corpus_version_id
      if (controller.signal.aborted) return
      const result = await client.companies({ corpus, historical: false, asOf: '' }, '', 0, controller.signal)
      if (controller.signal.aborted) return
      if (result.view.corpus_version_id !== corpus) throw new Error('The company page differs from the selected corpus.')
      resolved.current = { client, corpus: result.view.corpus_version_id }
      setCompanies(result)
      onSelectCorpus?.(result.view.corpus_version_id)
    })().catch(() => {
      if (!controller.signal.aborted) setError(selectedCorpus
        ? 'The selected filing corpus could not be verified. Select a published corpus in the filing explorer before using company context.'
        : 'Published company context is unavailable. The glossary and virtual account can still be used.')
    })
    return () => controller.abort()
  }, [client, selectedCorpus, onSelectCorpus])
  return { companies, error }
}
