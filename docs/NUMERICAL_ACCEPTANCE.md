# Audited numerical acceptance decisions

Migration 20 adds one append-only `regintel.numerical_acceptances` table over
[immutable numerical candidates](NUMERICAL_CANDIDATE_STORAGE.md). It records an
administrator's explicit ACCEPT or REJECT decision, the complete selected evidence
IDs, explanation, actor/authentication version, candidate/preparation hashes and
implementation configuration. Migrations 1–19 and public M1–M4 contracts remain
unchanged. No dependency, provider, service or required setting is added.

## Create and inspect a decision

Use the module branch, its explicitly selected module database and existing
[numerical runtime configuration](MODULE_HISTORY_AND_REVIEW_ACCESS.md). Migration
20 must be applied to that database. Keep the original M1 manual-test database
unchanged; automated verification uses owned disposable databases.

With current administrator authentication, obtain the actual saved candidate from
the backend. Review its entire word/cell proof and context, then explicitly send:

```text
POST /v1/admin/numerical/gates/{gate_id}/candidates/{candidate_id}/acceptance
{
  "candidate_id": "<same backend candidate ID>",
  "decision": "ACCEPT",
  "evidence_ids": ["<all exact gate evidence IDs, sorted and distinct>"],
  "note": "<actual administrator's review explanation>"
}
```

These are placeholders, not real approvals. The request cannot supply values,
checks, an actor or publication state. Unknown gate/candidate membership is
unavailable; disagreement between body/path candidate IDs conflicts. Ordinary API
startup without the optional numerical repository remains valid and returns an
explicit unavailable response at this private boundary.

The backend serializes decisions for the candidate and checks the current
administrator against PostgreSQL. For ACCEPT it freshly verifies the original
bytes, sealed parse, complete evidence, registry/metric/policy approvals and exact
context confirmation in the committing transaction. Approval tables remain
share-locked until commit. All sixteen mandatory categories for this supported
monetary-duration adapter must pass, the preparation must exactly reproduce the
candidate and the candidate storage configuration must still match. Notes cannot
override failures, missing support or unresolved context.

The SQL insert guard checks candidate/evidence/hash/actor membership, complete
matching checks and current approvals. The application additionally verifies
filesystem source/parse freshness; SQL does not parse the original PDF. UPDATE,
DELETE and TRUNCATE are rejected. The candidate itself remains unchanged.

The response contains `record` and the original `candidate`. ACCEPT stores
`ACCEPTED_UNPUBLISHED`, with `mandatory_m1_validation_complete=true` for this
versioned monetary-duration validation only. REJECT stores `REJECTED`, no fresh
checks and `mandatory_m1_validation_complete=false`. Rejection can record a
decision over a retained historical proposal even if its source is now unavailable.
Both keep `publishes_fact=false` and `published_corpus_version_id=null`.

Read the exact retained decision with:

```text
GET /v1/admin/numerical/gates/{gate_id}/candidates/{candidate_id}/acceptance
```

The programmatic interface is `NumericalAcceptanceRepository(source)` with
`save(NumericalAcceptanceRequest(...), administrator)` and
`get(candidate_id, administrator)`. Anonymous/learner access and stale, inactive
or demoted administrator identities are denied.

## Concurrent decisions and historical reads

There is one terminal decision per immutable candidate. Identical simultaneous
requests retain one original record/actor. A different decision, note or evidence
set conflicts; it cannot silently overwrite acceptance or rejection. Reconsidered
source/preparation versions require a distinct candidate and an explicit decision.

Exact retries and GET retain historical bytes and configuration after source or
implementation changes, subject to current administrator authorization. They do
not claim current source freshness. Future publication must freshly validate the
candidate and accepted decision again before committing its corpus membership.

## Publication and remaining work

This record is an audited acceptance decision over a proposal. It creates no
public accepted observation, corpus, amendment effect, graph/retrieval projection
or portfolio entry. It is not a legacy ValidationRun, and native word/cell proof
is never shortened or converted to an invented combined source span.

The separately versioned atomic publication writer and public evidence adaptation
remain required before M2 can consume these numerical values. All four retained
real inputs still have unresolved applicability/qualifier/basis/approval checks;
none receives a real review, candidate or acceptance in this checkpoint.
M3 actual content review, remaining M4 acceptance/evaluation work and final
research/fresh-clone handoff remain required. Runtime quotes remain unavailable
under the user's existing decision. Measured engineering checks are recorded in
`data/numerical-acceptance-validation-report.json`; authored fixtures are not real
filing review or research gold.
