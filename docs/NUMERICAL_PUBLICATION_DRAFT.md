# Numerical publication draft and projection preparation

The private numerical adapter can now prepare an unpublished corpus draft over
[audited numerical acceptances](NUMERICAL_ACCEPTANCE.md). It retains each complete
candidate/acceptance, exact native words and cells, Decimal quantity and immutable
filing metadata. An explicitly selected published legacy parent is retained in
full, with its historical observations, active set, lineage and effects intact.
The draft introduces no automatic replacement or timestamp-based supersession.

No migration, dependency, required setting or public M1–M4 schema is added or
changed. All twenty existing migrations remain frozen. Keep the original M1
manual-test checkout/database unchanged; automated checks use owned databases.

## Prepare the draft

Use the module branch and existing optional numerical runtime configuration.
With current administrator authentication, send actual accepted candidate IDs:

```text
POST /v1/admin/numerical/publication-drafts
{
  "idempotency_key": "<explicit canonical request ID>",
  "parent_corpus_version_id": "<current published parent ID, or null if none>",
  "candidate_ids": ["<accepted candidate IDs, sorted and distinct>"]
}
```

These are placeholders. The caller cannot supply entries, values, actor, checks,
configuration or publication state. Requests are bounded to twenty candidates and
a complete 64 MiB draft. Empty, duplicated, unsorted or mixed selections fail.
The current published head must equal the selected parent; there is no fallback
to another publication. Missing or rejected acceptances cannot enter the draft.

The backend checks the current administrator, takes the existing publication
transaction lock and holds approval/candidate/acceptance share locks. Within that
read transaction it rechecks original source bytes, sealed parse, complete evidence,
current registry/metric/policy/context confirmation and accepted configuration.
Every candidate's exact preparation must reproduce. Historical acceptance alone
does not authorize a fresh draft. New numerical addenda/corrigenda or filings
with declared parents are explicitly blocked pending the versioned amendment
adapter; existing legacy parent decisions remain readable and unchanged.

The response is `numerical-publication-draft-1`, with `state=UNPUBLISHED_DRAFT`,
`publishes_fact=false` and `corpus_committed=false`. The envelope has no newly
published corpus ID. This POST computes a read-only result: it creates no durable
build, observation, corpus, audit, graph/retrieval projection or ledger row.
The request key contributes to deterministic identity but is not reserved in a
database. The same request, actor/authentication and configuration reproduce the
draft; another actor/configuration produces a distinct draft identity.

Programmatic preparation uses `NumericalPublicationDraftRepository(source)` and
`prepare(NumericalPublicationDraftRequest(...), administrator)`. Ordinary startup
without numerical configuration leaves this private endpoint unavailable.
Anonymous/learner access and stale, inactive or demoted administrators are denied.

## Graph and retrieval preparation

The pure functions `prepare_numerical_graph(draft)` and
`prepare_numerical_retrieval(draft, encoder, embedding_manifest_sha256)` perform no
service or database writes. The latter accepts the existing server-side encoder
protocol. Runtime use requires the existing pinned BGE encoder/model manifest;
the private HTTP endpoint does not accept an encoder, vector or manifest hash.

Graph preparation retains the original legacy graph as its own versioned parent
snapshot, links that parent to the draft and adds the proposed numerical nodes,
accepted decision and all native word/role/geometry links. It does not rewrite
legacy graph payloads or relabel them as a new published corpus. Typed node ID
collisions and edges without retained endpoints fail. This composite unpublished
graph still needs the versioned publication/consumer implementation before use.

Numerical retrieval chunks carry role, phrase/chunk order, source page, table-cell
IDs and separate exact supports. Their text is explicitly reconstructed by joining
those supports; it is not a contiguous original source quotation. Full binding
and source geometry remain in the draft. Chunks stay within the actual encoder's
450-token target; oversized source words split at exact Unicode offsets without
silent truncation. Complete ordered coverage of every native phrase is mandatory.
Missing words/roles, reordered supports, wrong pages/cells and duplicate chunks
fail. Vectors must be finite normalized 384-dimensional values, with lexical
postings matching the same reconstructed text.

Inherited legacy retrieval retains exact source quotations and observation IDs,
derives chunk IDs for the selected draft and checks complete nonblank source
coverage. It requires the parent's exact embedding manifest; two model manifests
cannot silently mix. Projection preparation is bounded to 64 MiB and remains
non-publishing. It is not installed in Neo4j or pgvector and is not retrieved by
the existing public readers.

## Verification and remaining work

See `data/numerical-draft-validation-report.json` for measured checks and source
hashes. Positive filing/review/acceptance/embedding examples are labelled authored
engineering fixtures. They do not measure actual model effectiveness or confer
real filing/content approval. Legacy parent history tests cover ADD, CORRECT,
SUPPLEMENT, SUPERSEDE and REMOVE without changing their outcomes.

All four retained real inputs remain blocked. Actual applicability/qualifier /
basis/approval resolution, durable versioned builds, atomic publication, native
amendment effects and public evidence adaptation remain required before numerical
M2 use. M3 content review, remaining M4 acceptance/evaluation and final research /
fresh-clone handoff remain required. Runtime quotes stay unavailable as requested.
