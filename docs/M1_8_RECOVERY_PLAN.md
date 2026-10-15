# M1.8 — Checkpointed stages and verified failure recovery

Started 14 October from verified M1.7 source5de23f5/handoff0d8e991. Sequential
implementation and verified GitHub checkpoints are authorized. The existing
Windows/native API and private non-root Linux worker approvals persist. This
record preserves the implementation plan; measured closure on 15 October is below.

## Scope and authority

Preserve migrations0001–0008, immutable filing/parse/evidence/entity/candidate/
validation/review history, all algorithm/configuration identities and closed M1.9
acceptance/publication gates. Keep the existing parser job contract and terminal
results. Add a separate durable processing workflow for sealed parsed evidence:
entity resolution, candidate extraction and mandatory validation. Successful
processing means these stage results are sealed, including REVIEW/QUARANTINED
outcomes; it does not confirm reviews or publish corporate observations.

An administrator submits a parse ID, explicit metric IDs and a canonical request
idempotency key. Queue messages contain only a backend job ID. PostgreSQL owns
the immutable request/configuration/actor, mutable progress, append-only attempt
history, frozen stage inputs, immutable output checkpoints and replayable dispatch
intent. A matching request replay returns the original job. Different data under
the same key conflicts; a new request preserves earlier jobs and audits.

## Transaction and recovery boundaries

Freeze each stage's complete validated source/input and configuration before its
work. Reuse that input on retries. Changed installed configuration, revoked actor
or changed audited dependencies causes an explicit terminal failure, requiring a
new supported job rather than silently replacing a snapshot. Each stage has one
checkpoint; the domain result and checkpoint commit in the same transaction.
The existing repository gates remain responsible for source/authentication and
semantic correctness. Add trusted connection factories and completion hooks to
repository wiring; preserve the frozen algorithms, models and SQL gates.

Serialize a workflow with a PostgreSQL session advisory lock and fence writes
with its current attempt generation. Loss of a worker/database session releases
the lock; a replacement attempt resumes unfinished stages, skipping sealed
checkpoints. A late old attempt cannot attach or alter a checkpoint. A crash after
the last checkpoint but before job completion only requires completion bookkeeping.
Temporary database/broker errors retain durable intent and retry with bounded
backoff. Recovery dispatch skips a currently locked job and can resend an orphaned
unfinished job even after a prior successful broker send. Duplicate deliveries
are expected; execution is not claimed exactly once.

## One approved container, preserved parser identity

Keep the parser's existing109-package virtual environment and descriptor. Install
the existing locked `entities` extra in a second virtual environment inside the
same image, using the same source and pins. The existing Celery worker invokes a
fixed module in that environment with a canonical job ID; no shell, filing text,
client path or credential is part of the command. This avoids changing the parser
SDK's complete installed-package identity. Native API/frontend and existing
PostgreSQL/Redis/Neo4j services retain their placement and private bindings.

No new dependency pin, provider/model, paid usage, host software, service, port or
model download is planned. A phase-required image rebuild must verify both exact
package inventories, source/configuration fingerprints, non-root/read-only mounts,
offline parser identity and real stage execution. D: free space measured38.70GB
and C:16.68GB before work; data services are healthy and primary schema1–8 is
applied. Retain original Docker data and the historical image/backup.

## Verification and publication

Test typed inputs/state transitions, authorization, source membership, replay/
conflict/concurrency, frozen and stale inputs/configurations, rollback of result
plus checkpoint, late-generation writes, temporary storage/broker failures and
real Celery task registration/retry. Run fresh disposable database tests before
applying append0009; preserve earlier migration checksums. Verify the real Premier
source through the authenticated API and the rebuilt Linux worker, including
actual duplicate consumption and abrupt in-flight recovery, without replaying or
rewriting earlier source/parse jobs. Record exact stage IDs/input/configuration
hashes, audit/attempt counts, preserved earlier snapshots and zero authority.

Complete relevant backend/frontend/static/browser checks and staged byte/secret
review; update CURRENT_STATE, measured metadata and the next continuation prompt,
then commit/push normally to existingmain and inspect that source's hosted CI.
Real assets/credentials/models/cache/database state remain outside Git.

Primary implementation references: [Celery5.6.3 task acknowledgements and
idempotency](https://docs.celeryq.dev/en/stable/userguide/tasks.html),
[uv extras and exact environment sync](https://docs.astral.sh/uv/concepts/projects/sync/)
and [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/).
These support implementation choices, not measured project outcomes.

## Measured closure — 15 October

M1.8 is complete as bounded processing/recovery. The measured report records two
actual crash recoveries on the existing Premier parse: before a checkpoint with
a test-owned registry-lock barrier, and after the first checkpoint committed.
Both complete at generation 2 and retain frozen input/committed history. Consumed
terminal duplicates preserve completed state. Source/domain/review snapshot
hashes stay unchanged; all acceptance/observation/corpus counts remain zero.

The real multi-record source exposed an order comparison missed by the initial
single-record fixtures. Applied0009 is preserved; append0010 and a deliberate
two-record regression separate traversal order from sorted evidence membership.
The failed first probe remains immutable. A separate immediate-consumer test
exposed and fixed a producer lock race; final completion rechecks authorization
even when all stage checkpoints already exist.

The final 42-case processing storage suite passes 185.61s. Full 441 database cases
passed before the last refinements. Local runner1747backend/6Windows skips,
212frontend/3Chromium and final scoped static checks pass. Source CI publication
status is recorded in CURRENT_STATE/PHASE_LOG. Final image 5ea1bac1... verifies
82 source files in each environment, unchanged 109-package parser identity and
77stage packages matching the existing Linux entities export exactly. No new
dependency pin or environment variable. Both migrations are applied with earlier
bytes preserved. Full hashes, actual output IDs and inventories are in
`data/processing-recovery-report.json`.

Admin routes are `POST /v1/admin/processing/jobs`,
`GET /v1/admin/processing/jobs/{job_id}` and
`POST /v1/admin/processing/jobs/{job_id}/dispatch`. Submit a canonical request key,
sealed parse ID and sorted distinct explicit metric IDs. Actor/configuration
and stage inputs are server-owned. Completed request replay returns the saved
job; conflicting payloads require a new key. A terminal failed request is retained.
After infrastructure recovery, an administrator can redispatch unfinished jobs,
or an operator can run `python -m regintel.processing.cli dispatch --env-file .env`
with optional `--job-id` and bounded `--limit` (1–100). This command does not
reparse or replace the old ingestion job contract. No exactly-once guarantee.

Successful processing seals outputs; it never accepts a fact, creates a staged
review or publishes a corpus. M1.9 must freshly validate supported reviews and
current dependencies before atomic publication. No research effectiveness,
new real numeric/relation positive, macOS/ARM or fresh real-clone claim.
