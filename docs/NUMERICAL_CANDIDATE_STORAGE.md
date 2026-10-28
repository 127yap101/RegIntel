# Immutable numerical candidates

Migration 19 adds `regintel.numerical_candidates`, an M1-owned append-only proposal
store. It retains the complete reviewed numerical preparation and a separate
small record containing its hash, backend identity, configuration and actual
submitting administrator. It writes no accepted fact, acceptance audit, corpus,
graph, retrieval projection or ledger entry. Existing migrations 1–18 are frozen.

## Create and inspect a candidate

Use the module branch and existing
[numerical runtime configuration](MODULE_HISTORY_AND_REVIEW_ACCESS.md). Migration 19
must be applied to the explicitly selected module database. Keep the original
M1 manual-test database unchanged; automated verification uses disposable
databases and does not migrate it. No new environment variable, provider,
dependency or service is required.

With a current administrator session, first request
[the publication input](NUMERICAL_PUBLICATION_INPUT.md):

```text
GET /v1/admin/numerical/gates/{gate_id}/publication-input
```

Only `READY_FOR_ADAPTER` supplies `proposed_input.id`. Then explicitly create:

```text
POST /v1/admin/numerical/gates/{gate_id}/candidates
{"gate_run_id":"<selected gate ID>","prepared_input_id":"<backend proposed_input.id>"}
```

These are placeholders; use actual local backend IDs. The request cannot supply
a quantity, proof, actor, approval or acceptance flag. Body/path gate disagreement
conflicts. A missing/rejected review, unresolved check, changed source/approval
snapshot or outdated selected preparation cannot create a candidate.

The backend locks approval tables, checks the current administrator, verifies the
original bytes/parse/evidence/registry/metric/policy and prepares the exact input
inside the committing transaction. The SQL insert guard independently checks
gate/review/quantity/proof membership, sixteen passing preparation categories,
current approval records, exact hashes/IDs and non-authoritative flags.

The response contains `record` and `preparation`. The state is always `CANDIDATE`;
`acceptance_eligible`, `mandatory_m1_validation_complete` and `publishes_fact` stay
false. All source words/cells and exact Decimal values are retained. No combined
source span is invented to fit the old sixteen-span contract.

Inspect the saved candidate with:

```text
GET /v1/admin/numerical/gates/{gate_id}/candidates/{candidate_id}
```

The matching programmatic interface is `NumericalCandidateRepository(source)`
with `save(NumericalCandidateRequest(...), administrator)` and
`get(candidate_id, administrator)`. Ordinary API startup without the existing
numerical repository/runtime remains valid and leaves these private routes
unavailable. Anonymous/learner access is denied.

## Retries and history

The candidate identity is deterministic per backend prepared-input ID. An
advisory transaction lock serializes concurrent requests, so identical retries
return one original record/actor. A different gate cannot reuse that input.
New preparation versions produce distinct candidates without overwriting old
bytes. SQL rejects UPDATE, DELETE and TRUNCATE.

An existing exact retry or GET is a historical read, including after source or
configuration changes. It does not claim the source is fresh now or create
another record. The original preparation and actor remain intact. The remaining
acceptance/publication writer must freshly verify the actual source/context
before accepting anything; a historical candidate is not write authorization.

## Verification and remaining work

See [the measured report](../data/numerical-candidate-validation-report.json) for
the actual completed tests. Positive cases use authored words/PDFs and stored
context decisions in owned PostgreSQL databases. They are not real-filing human
approval or research gold. The four retained real inputs remain unresolved and
cannot supply a ready prepared input; no real candidate is created by this work.

This completes candidate proposal storage. Real source applicability/qualifier /
basis and approval resolution, the versioned immutable acceptance/atomic
publication writer and public evidence-consumer adaptation remain required
before real numerical M2 comparisons. The public M1–M4 contracts and original
manual-test data remain preserved. M3 actual content review, remaining M4 work,
research evaluation and fresh-clone handoff are still required. Runtime quotes
remain unavailable under the user's existing decision.
