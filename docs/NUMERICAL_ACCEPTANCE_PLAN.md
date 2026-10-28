# Reviewed numerical acceptance before publication

28 October 2026. Continue the approved M1 numerical producer integration from
`88415ee`; all three exact-source CI jobs pass in run 40637839300. Preserve the
original M1 checkout/database, public module interfaces and migrations 1–19.

Implement an explicit administrator ACCEPT/REJECT decision over one immutable
numerical candidate. An acceptance revalidates the original source bytes, sealed
parse, complete native word/cell proof, current approvals, context confirmation
and all sixteen mandatory monetary-duration checks in the committing transaction.
It must reproduce the candidate's exact preparation and current storage contract.
No unresolved check can be overridden by a note. A rejection records a decision
over the retained proposal without claiming fresh validation.

Migration 20 adds one append-only decision table with actor/authentication,
candidate/preparation/configuration hashes, exact evidence membership and checks.
The SQL guard verifies source/candidate/check/approval membership and prevents
rewriting, deletion or truncation. Serialize decisions per candidate: identical
concurrent requests retain one original actor; conflicting decisions fail.
GET and exact retries are historical reads after current-admin authorization.

The client supplies only candidate ID, decision, exact evidence IDs and note.
Private create/read endpoints stay under the selected gate/candidate. Values,
actors, checks and publication state are server-owned. Preserve historical
candidate and decision bytes/configurations.

An ACCEPT is explicitly ACCEPTED_UNPUBLISHED, validates only this supported
monetary-duration adapter and creates no accepted public observation, corpus,
amendment effect, graph/retrieval projection or portfolio change. Publication must
freshly validate again and atomically establish the observation's corpus/evidence
membership. Its versioned writer and public evidence adaptation remain necessary.
Do not cast this record to a legacy ValidationRun or truncate native proof.

Verify authored positive/rejected cases, concurrent identical/conflicting writes,
freshness/role failures, exact evidence membership, historical replay, direct SQL
tampering and rollback. Run shared M1–M4 HTTP regressions and static/generated
checks. Separately replay all four real blocked inputs; create no real reviews or
decisions. No dependency, required setting, quote feed or paid service is added.
