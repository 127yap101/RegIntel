# M1A — Ingestion and exact evidence

Started2026-10-06. The user explicitly waived the presentation gate and authorized
M1A. This is an execution plan subordinate to the finalized specifications. The
deck has not been verified or corrected; the waiver changes the implementation
gate, not the factual presentation status.

## Scope and sequence

| Phase | Work | Acceptance before advancing |
|---|---|---|
| M1.1 | Append ingestion/version/source/page/block/table/cell/evidence/candidate/fact/relation schemas and typed models | Shape/context/membership/immutability tests; safe upgrade/repetition; exact Decimal storage; independent review |
| M1.2 | Admin upload, byte hashing, scoped deduplication and PostgreSQL-authoritative durable dispatch intent | Authentication/revocation, malformed/oversized input, concurrent duplicate and metadata-conflict cases, broker failure/replay and live worker delivery |
| M1.3 | Versioned Docling adapter, exact structure/provenance/coordinates, one explicitly configured supported OCR engine | Actual native/table/raster parsing; rotation/crop transforms; OCR tuning/limitations; source/config/model hashes; no fabricated confidence |
| M1.4 | Atomic evidence persistence, evidence API and authenticated full/range original PDF access | Exact stored spans/cells/source version, access before bytes, range semantics, immutable validators and visually inspected source highlights |

M1B still owns entity-resolution behavior, model candidates, evidence/context
acceptance, reviewer workflows, full recovery, amendment decisions and publication.
M1.1 schemas do not establish those capabilities. M1C/M2 own later company pages,
retrieval and viewer experiences. A representative real public seed filing is
required for M1A acceptance; synthetic fixtures alone cannot establish that result.

## M1.1 choices and preservation

Reuse canonical UUIDv4/string-Decimal/shared evidence contracts and psycopg; no new
dependency is needed. Append0003 in the owned regintel schema; never rewrite the
applied0001/0002. Separate source bytes/hash, logical filing, immutable filing
version, parse provenance and future corpus identity. Keep exact block text,
Unicode code-point spans, contextual cells and page-local raw geometry.

Composite keys/references must prevent a valid UUID from a different filing,
parse, page or table satisfying source membership. Reparse appends new provenance
and leaves old evidence traceable. Preserve negative media/crop origins and
rotations0/90/180/270; canonical highlights use unrotated PDF points/bottom-left.
Cross-page support consists of separate evidence records. Blank/dash stays raw and
missing; normalized authoritative numeric columns use NUMERIC, never floats.

The finalized docs do not prescribe complete column lists, upload limits, status
enums or storage layout. Document implementation choices in M1_1_SCHEMAS.md and
later phase records, preserving the fixed authority/context rules. Existing
migration tests must track default migrations without weakening two-file atomic
probe tests; disposable cleanup stays confined to its new test database.

## Worker execution for M1.2 — approved2026-10-06

Current Celery documentation excludes native Windows workers. The approved host
is Windows, while architecture §11 specifies native macOS applications. A
supported worker placement exception is therefore necessary before M1.2.

Proposed action: add one non-root Linux Celery application-worker container to the
existing Compose project/network, using the existing PostgreSQL/Redis services.
FastAPI and frontend remain native Windows. The worker has no published port,
Docker socket or separate database/broker. Source/artifact mounts are confined to
ignored project storage; make source access read-only where stages permit it.
Select an official digest-pinned Python3.12 base and exact tested Celery/Redis
transport pins only after approval. Record image/model/library licenses/hashes.

PostgreSQL commits ingestion state and dispatch intent together. Queue payloads
contain bounded IDs/config references and JSON serialization, with duplicate
delivery handled by database identity/transactions. Test native producer→Linux
worker, Redis interruption/recovery, worker restart and concurrent duplication.
Redis redelivery means exactly-once execution cannot be promised.

The user explicitly answered “Approve the Linux worker container plan” on
2026-10-06. This approves the documented application execution exception for
Celery/Docling work; native API/frontend and existing services remain as specified
above. At approval time no worker image/dependency/infrastructure change had yet
been made. Implementation and tested pins still require phase verification.

Primary references: [Celery Windows FAQ](https://docs.celeryq.dev/en/stable/faq.html#windows),
[Celery Redis transport](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html),
[Docling installation](https://docling-project.github.io/docling/getting_started/installation/).

## Parsing dependencies and source acquisition

Docling and one supported OCR engine belong to M1.3; metadata-only candidates are
not installed/tested choices. Inspect actual Python3.12 platform wheels and all
model licenses, freeze required artifacts in ignored local storage and measure
native/OCR behavior before claiming support. OCR applies only where native text is
inadequate. Do not install future entity/embedding/provider packages here.

Acquire one verified public filing within the four-company seed scope, retain its
source URL/date/type/SHA256 and explicit parent metadata if present, and keep the
PDF out of Git. Verify representative text/table/evidence manually. Neither the
approximate eight-document specification nor a synthetic manifest proves real
filing availability or reviewed gold annotations.

## Closure

Run meaningful targeted checks, the disposable live gate and full existing checks
for implemented changes. Keep database activation after migration review/live
verification. Update current state, dependencies, phase log and continuation at
each verified phase. Do not claim M1A complete until a real filing reaches exact
persisted evidence and authenticated source access with measured limitations.
No provider calls, remote pushes or local commits are authorized.
