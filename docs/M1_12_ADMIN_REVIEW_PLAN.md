# M1.12 — Administrator filing, review and publication workspace

Started 16 October 2026 from verified main `6f8bd6b`. Sequential implementation,
verification and normal GitHub checkpoints remain authorized. Scope is M1.12;
M2–M4 and held-out research evaluation remain later work.

## Existing boundaries and necessary adapters

Existing upload, processing, validation/review, exact administrator evidence/PDF
and publication APIs own all writes. Reuse their current authorization, immutable
records, source/context gates, idempotency and atomic publication. No direct
candidate/observation editing, gate override, inferred effect/date or automatic
publication. Preserve migrations 0001–0011 and frozen parsing/entity/candidate/
validation/publication/retrieval algorithms and hashes.

The current APIs require manually supplied IDs and have no bounded work queues.
Add a separate read-only administrator adapter for paginated filing jobs,
processing jobs, validation audits and publication builds; expose a paginated
validation review view using verified frozen candidate/source/run bytes. Include
all prior final candidate decisions, even when made against an earlier gate run.
An old decision cannot be overwritten. The adapter rechecks the current admin
account in a read-only transaction, never writes authoritative state and uses
fixed SQL with bounded pagination. No migration or dependency is required.

## Browser workflow

An explicit administrator workspace has memory-only authentication and works
before any corpus is published. Learners remain denied by server authorization.
Show and refresh filing/processing progress, upload a bounded original PDF with
explicit metadata, and submit/recover processing through existing APIs. Do not
infer parent, date, metric or company identity from filenames.

Review screens show original proposal text, direction, raw/normalized financial
context, all mandatory checks, exact support and original PDF regions. Filter
quarantined/review/pass results. Approval requires eligible current gates and a
reviewer note; rejection remains audited. Submitting a decision stages it for
publication; it does not publish or mutate accepted facts. Preserve stable retry
IDs for writes and clear stale private data on selection, logout or expired auth.

Create a publication draft from explicit reviewed selections and an explicit
parent corpus. Show the approved manifest, unresolved parents and amendment
scope before a separate Publish action. Supported corrections use new reviewed
candidates plus explicit evidence-backed lineage/effects; existing observations
stay immutable. Provide typed amendment forms with exact evidence spans and
optional supported effective dates. No automatic latest-filing replacement.

## Verification and closure

Add separate generated admin schema/TypeScript contracts; preserve earlier
exports. Test current-role denial/revocation, empty/unpublished workspaces,
pagination, source/run/hash drift, quarantine approval blocking, historical final
reviews, Decimal/context rendering, stale responses, retry identity, review and
publication failures, exact source rendering and narrow layouts. Test actual
PostgreSQL adapter behavior in a disposable database and actual browser-to-API
read-only navigation on the existing real filing. Keep authored write scenarios
separate from real filing evidence; do not approve/publish new real facts merely
to demonstrate the UI.

Run relevant backend/frontend/browser/static checks, review the diff and secrets/
assets, verify preserved bytes, update CURRENT_STATE and handoff, commit/push a
reviewed source checkpoint and inspect its exact-source hosted checks. No paid
model call, new infrastructure, public port or worker rebuild is planned.


## Implementation and local verification

Implemented the separate `regintel.admin` read-only adapter and generated admin
schema/types. Four queues and review pages are limited to 25 items/request
(browser requests 20); offsets stop at 10000. Metric catalog is explicitly
bounded at 100. Read transactions recheck active current admin role/version,
use repeatable-read/read-only mode and a 15-second statement timeout. Frozen
domain repositories verify candidate/source/run bytes and expose older final
reviews plus existing acceptance identity. No new mutation endpoint.

The browser uses memory-only admin authentication, strict AJV/Pydantic wire
contracts, source/version binding, Unicode code-point support checks and
original-PDF SHA256 validation. The existing PDF viewer retains its 64 MB and
16-million-pixel limits; upload's existing independent limit is 64 MiB.
Review cannot override mandatory failures or rewrite a final decision.
Publication uses reviewed selections, an explicit parent, optional exact
lineage/effect forms, an inspected immutable manifest and a separate publish
action. Inputs clear stale builds/sources; logout/revocation clears private state.

Measured checks: 1932 native backend/six disclosed Windows skips in 495.16s;
30 new API cases; six disposable PostgreSQL cases in 13.41s; final complete
frontend lint/types/build, 254 unit tests in 77.85s and 24 Chromium tests in 1.4m.
Ruff 199 files/mypy 131 sources and shell/actionlint/Node checks pass. The combined
native runner stopped at four test lint errors after its passing backend stages;
test typing was corrected and the complete frontend command passed. Detailed
failed attempts and fixes are retained in PHASE_LOG and the measured report.

The read-only real proof `.cache/admin-browser-9daebf6d16ab4516bfb2e7550ee2feba` verifies the existing
Premier parsed job, completed workflow, prior immutable review/accepted
observation, all sixteen checks, PDF.js original page 3/one region, 375px layout,
published scope and private clearing. Zero authoritative writes; all original
source/processing/publication snapshots remain unchanged. Original stopped data
containers were restored from their volumes; proof servers are stopped.

Protected-byte audit passes all 113 files, including every migration 0001–0011,
specifications 00–10 and frozen domain code/locks. Processing configuration stays
`bacb112415f5728f813738f353f6c2765a9f0135177460e9497ab00e445b2dd6`. No dependencies,
environment variables, migrations, infrastructure, worker rebuild or paid calls.
Source commit/push and exact-source hosted verification are pending.

This closes local UI engineering only. Authored writes are not real-filing
accuracy results; the corpus still has one conditional narrative and no
numeric/relation positive or actual amendment pair. Entity/metric/policy registry
administration remains through existing APIs/CLI. Gold/held-out effectiveness,
macOS/ARM and a fresh real-source clone remain unverified.


## Source publication and hosted closure

Source `4114407839a9a319fcf075a847c976a23dc2bfa9` is pushed normally to existing main.
Exact-source [run 38908935402](https://github.com/127yap101/RegIntel/actions/runs/38908935402) completed SUCCESS:
Windows foundation, Ubuntu foundation and Linux data infrastructure. Complete
foundation/database commands, fresh migration 1–11 apply/replay, seeded-role
authentication and service-restart persistence pass. Evidence is public run/job/
step conclusions; raw job logs were not accessed and no per-test hosted counts
are inferred. All 27 measured source fingerprints match the verified commit.
This final follow-up changes documentation/report metadata only.

M1.12 and bounded M1/M1C implementation are complete. M2 is next; M2–M4,
integration, broader real-source coverage and held-out effectiveness remain
unfinished. Earlier pending notes describe the local checkpoint before this
hosted closure; limitations and repaired attempts remain disclosed.
