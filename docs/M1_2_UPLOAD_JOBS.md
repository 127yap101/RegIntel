# M1.2 — Admin upload and durable jobs

Started2026-10-06 after verified M1.1. The user approved the Linux worker container
exception; deck gate is waived and the presentation remains unverified. Preserve
M0/M1.1, existing accounts/secrets and data volumes. This phase implements upload
and source verification, not Docling/evidence acceptance or corpus publication.

## Recorded choices before implementation

- POST /v1/filings accepts an application/pdf streamed body and bounded filing
  metadata in query fields. Check the existing DB-backed admin dependency before
  reading bytes; avoid loading an entire multipart upload before authorization.
  Support64MiB maximum/2000 pages, configurable only within bounded settings.
  Preserve PDF bytes; reject encryption, malformed/truncated PDF and bad input.
- Source files use the existing content-addressed sha256/<hash>.pdf key beneath
  explicitly configured ignored data/uploads. Stage each upload in an exclusively
  created server UUID path, hash while streaming and publish complete bytes with
  atomic exclusive hard-link creation. Reject links/junctions/conflicting content;
  filenames never select paths. Worker rechecks bytes/hash. No public file serving.
- Blob identity is the exact byte hash. Deduplicate logical filing/version/job only
  when supplied metadata and processing configuration also agree. Identical bytes
  with conflicting metadata return a conflict; no silent company/filing merge.
  Missing publication/parent/company identity remains explicit.
- PostgreSQL creates filing/version/job and durable dispatch intent transactionally.
  Redis/Celery delivery is derived; broker outage leaves replayable intent. Queue
  payload contains only a canonical job ID, uses JSON and no runtime model tools.
  Dispatch after commit; duplicate delivery is serialized/idempotent at storage.
- M1.2 worker produces SOURCE_VERIFIED or a sanitized failure code, with source
  hash/PDF verification measured. This is not parsing/evidence readiness. Later
  M1.3/M1.4 extend processing stages; M1.8 remains full checkpoint/recovery work.
- Add one non-root worker on the existing network, no new broker/database/port,
  mount confined source storage read-only and keep native API/frontend. Install
  exact tested celery[redis]5.6.3 and promote already installed pypdf6.19.0 to runtime
  for PDF validation. Reuse uv0.12.23; no host tool/compiler installation.

## Measured image metadata; execution not yet tested

Official Python3.12.15-slim-bookworm OCI index:
sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258.
Official Astral uv0.12.23 OCI index:
sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21.
Both contain linux/amd64 and ARM64; metadata inspected via credential-free project
Docker config. Worker Python patch3.12.15 differs from native3.12.14 explicitly;
both stay in the fixed3.12 series. Record actual build/runtime/lock pins after
testing. A first metadata command used a nonexistent config location and missed
plugin discovery; corrected to existing .cache/docker without changing settings.

## Acceptance

Auth/revocation before upload, exact hash/immutable bytes, missing/incompatible
metadata, malformed/oversized PDFs, duplicate/concurrent upload and dispatch
failure/replay, repeated delivery, real native producer→Linux worker, confined
mounts/non-root/no exposed port, preserved primary accounts/checksums, schema
upgrade/default/live/full checks. Reuse the controlled Premier Energies source.
No exactly-once, parser/evidence, publication or research-result claim is allowed.

Primary references: [Celery5.6.3](https://pypi.org/project/celery/5.6.3/),
[Celery Redis transport](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html),
[uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/),
[Python image source](https://github.com/docker-library/python).

## Implementation and verification checkpoint

The61-package lock is installed. Celery5.6.3/Redis transport6.4.0 are runtime
dependencies; existing pypdf6.19.0 moved from dev to runtime without a version
change. Metadata resolution repaired legacy package metadata warnings without
install failure. No compiler/system tool/model/provider was installed. The pinned
Linux image builds43 production packages using Python3.12.15/uv0.12.23.

0004_jobs appends immutable ingestion keys, mutable jobs with audited submitted_by
and immutable anchors, and dispatch intent. Source/version/job/intent creation is
atomic, hash-serialized and repeated only for matching metadata/config. Admin and
auth version are checked before stream and rechecked under a user share lock
before committing identities. New configurations append jobs. Source files
published before a failed transaction remain ignored unregistered blobs; no unsafe
orphan cleanup occurs in this phase.

Upload dispatch is bounded to its own job. Explicit regintel-dispatch replays
unsent batches (maximum100). Send-before-commit can produce repeated delivery;
session locks and terminal no-ops preserve one outcome. Ordinary OperationalError/
InterfaceError are sanitized and explicitly autoretried with task.max_retries=None
and backoff capped60s. Source failures remain terminal. Setting only
retry_kwargs.max_retries=None does not override Celery's default3 retries; the
actual registered task test verifies six attempts to success.

Independent source review identified/fixed retry acknowledgement, unbounded source
hashing, per-request backlog dispatch and transaction auth recheck. Tests caught
default migration-count assumptions and no-store headers. The isolated0003 failure
probe still checks its own migration directory. Final local runner exits0:373
backend/212 frontend/browser3,61-package lock, Ruff63 files/strict mypy44 sources.
Separate live gate passes103/373 deselected in144.12s, including actual connection
loss after successful delivery, rollback/replay and one terminal result. Its new
disposable regintel_test_m0_3_2d13557be5194298936c9e0bc4a0d1b2 was removed.

Primary activation then applied only0003/0004, status[1,2,3,4]/pending[]. Both seeded
roles pass authentication checks. Original0001/0002/0003 hashes match; frozen0004
UTF8/LF SHA256:e2be2e54071e776ff5155086333bdff524510f654138ccc0a0aef82e0894b534.
Never edit applied migrations. Real producer→Linux worker acceptance is pending.

Both Compose wrappers expose worker-build/up/status/restart/stop explicitly. The
ingestion profile keeps foundation commands scoped. Source storage must exist
before worker startup. Worker uses a read-only source mount, UID/GID10001, a
read-only root, dropped capabilities/no privilege gains and no port. Windows is
the measured target. Unix reproduction requires readable source files and
traversable directories (public-source contract:0644/0755); creation currently
inherits umask, so macOS/Linux bind-mount reproduction is unverified. Credential
file permissions are unchanged.

The Windows runtime acceptance helper owns a native loopback API process, briefly
stops/restores only Redis for a fresh job, replays intent, checks the original
three-page source/hash, and verifies actual duplicate consumption across a graceful
worker restart. Existing terminal records are preserved; abrupt in-flight crash
recovery belongs to M1.8. The helper is under final review; no runtime pass yet.

## Closure — verified2026-10-06

The reviewed runtime probe now passes both fresh-upload/outage and existing-job
replay modes. Real jobb2aaaf4d-c2fc-4537-9414-3e6dad710171 verifies the original
196270-byte Premier PDF, exact source SHA256 and3 pages with1 attempt. Redis was
briefly offline at submission; intent stayed durable, replay succeeded,2 terminal
duplicates were actually consumed/drained, the same worker container restarted
with a later StartedAt, and a post-restart duplicate was consumed/drained without
changing the result. Original metadata/missing publication/parent/entity remain
explicit. The owned native API stopped, services restored/healthy, records retained.

Worker isolation/runtime inspection: UID/GID10001, LinuxPython3.12.15,
Celery5.6.3/pypdf6.19.0, read-only root and source mount, no ports. Tested image
sha256:c3774067af7d7ecb3729fa847c27a48a39c8c32003cebf116a1061991c6639d8.
The controlled data manifest records actual filing/version/blob/job IDs/config.

Final runner exits0:61-package lock, drift checks, Ruff64files/strictmypy45sources,
373 backend/103 deselected (15.12s),212 frontend/lint/types/build, Chromium3 (15.3s).
After independent M1.1 review strengthened masked negative tests, selected29 live
constraint cases pass27.88s; only new disposable
regintel_test_m0_3_ebb1ff0cb22249a2a824315496143c4c was removed. The full103 live
gate already passed; no application/SQL behavior changed afterward. Explicit
check-migrations --test-file selection is confined to an existing integration file;
default still runs all live tests. Its lint/format/mypy pass.

All15 original contract/specification/0001/0002 hashes match the original snapshot;
applied0003/0004 are frozen. M1.2 complete. No parsing, evidence persistence,
acceptance, publication, research improvement, abrupt crash recovery, hosted CI
or macOS/ARM64 reproduction is claimed. Next M1.3 follows its prepared plan.
