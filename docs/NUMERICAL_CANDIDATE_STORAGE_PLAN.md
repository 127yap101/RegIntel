# Immutable numerical candidate storage

28 October 2026. Continue the approved numerical publication adapter from
`6943817`; all three exact-source CI jobs pass in run 40561874583. This step persists
the reviewed, complete input already produced by the read-only preparation.

Add one append-only PostgreSQL table in migration 19; preserve migrations 1–18 and
the original main checkout/database. Keep this an M1-owned candidate proposal,
not an accepted observation, legacy ValidationRun or published corpus. All
acceptance/M1-validation/publication flags remain false. Preserve the complete
word/cell proof and exact Decimal context.

The private creation request supplies only the selected gate ID and the prepared
input ID returned by the backend. A current administrator must explicitly create
the candidate. New writes freshly recheck the original source, sealed parse,
evidence and approval snapshots in the committing transaction; lock approval
tables until commit. Failed/unresolved context or missing/rejected review cannot
create a candidate. Callers cannot supply values, actor, approval or balances.

Use a deterministic candidate identity per prepared input. Serialize concurrent
requests for that input so identical retries retain the original record/actor.
A different selected gate or input conflicts. Existing exact retries and GET are
historical reads, including after source/configuration changes, and create no new
state. Future acceptance must perform fresh validation again. New preparation
versions append distinct candidates; old bytes/configurations remain readable.

Store canonical preparation bytes/hash and a separate small candidate record /
hash, with source/gate/review foreign keys and current-admin checks. SQL insertion
guards verify exact gate/quantity/proof/review membership, all sixteen passing
preparation categories and non-authoritative flags. Reject UPDATE/DELETE/TRUNCATE.
Add private create/read endpoints without changing the public M1–M4 contracts.

Verify actual PostgreSQL writes, transaction rollback, identical/conflicting
concurrency, actor retention, current-role enforcement, direct SQL tampering,
historical replay and no fact/audit/corpus writes. Replay the four retained real
inputs separately; they must still be blocked and create no real candidates.
Use authored positive fixtures, not invented real approvals. No dependency,
provider, service, public port or required environment variable is added.

This completes durable candidate storage only. The separately versioned immutable
acceptance/atomic-publication writer and public evidence-consumer adaptation
remain required before these candidates can supply real M2 values.
