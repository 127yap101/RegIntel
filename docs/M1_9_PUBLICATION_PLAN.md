# M1.9 — Amendment-aware publication implementation plan

Started 15 October from verified M1.8 source80f4127/handoff74ab4a1. Sequential
implementation, relevant verification, commits and normal pushes are authorized.
The approved Windows/native API and one private Linux worker placement persist.
This is a plan; no publication, amendment result or effectiveness is claimed.

## Authoritative state and acceptance

Preserve applied0001–0010, frozen parsing/entity/candidate/validation algorithms,
raw candidates and every existing review/workflow/source. Add explicit immutable
publication requests and complete approved corpus manifests. A candidate must
belong to its supplied sealed run. Recompute the current sixteen-check gate from
the complete sealed source and current audited dependencies. PASS is eligible;
REVIEW is eligible only when extractive confirmation is its sole unresolved
check and a source-backed APPROVE_FOR_PUBLICATION review exists. No mandatory
failed/ambiguous check can be overridden. Retain the original review's older
validation/configuration reference separately from the fresh publication gate.
Never overwrite or duplicate an old final review to make it appear current.

An observation binds candidate/run/parse/filing, complete exact support and
context, fresh validation snapshot/configuration, original review where required,
acceptance actor/audit, normalized Decimal quantity and its first corpus version.
Raw quantitative candidates remain unchanged. Later corpus membership references
the immutable original observation instead of cloning it. Unknown dates stay
unknown. No page-only citation, model decision or timestamp grants authority.

## Lineage, effects and views

An administrator records source-backed parent/child filing-version lineage with
both issuer identities, exact child parent-reference and an audited explanation.
Both original sources must exist; self-links/cycles/cross-issuer links fail.
Explicitly reviewed ADD/CORRECT/SUPPLEMENT/SUPERSEDE/REMOVE effects bind this
lineage, affected parent observations, new child observations and exact amendment
support. Removal requires explicit removal wording. Replacement effects deactivate
only their named old observations. Addition/supplementation keep earlier facts.
Overlapping competing effects fail for review; no implicit reconciliation.

Historical views retain every observation. Active views use recorded effects for
the requested corpus. Filing-date as-of views require supported source dates and
explicit effect dates; missing temporal support yields an explicit unavailable
result, not an inferred date or latest-row-wins result. Financial periods are
independent of source/effect dates. The existing shared SUPERSEDE spelling stays.

The controlled real corpus currently has one Premier addendum, whose referenced
parent is not ingested. Do not invent that parent or a real amendment effect.
Verify the generic amendment path with labelled authored multi-filing fixtures;
keep real parent linkage unresolved and disclose its limit. The independently
supported conditional narrative can test publication without pretending an
amendment pair or numeric/relation positive has been measured.

## Publication and derived projections

Use a recoverable BUILDING → PUBLISHED workflow over an immutable, admin-approved
manifest. PostgreSQL owns authority. Keep approved build records invisible to
consumer reads until publication. Prepare version-scoped Neo4j and pgvector/BM25
projections from that exact manifest, verify their identities/counts, then publish
the PostgreSQL corpus/head atomically after fresh authorization/dependency checks.
The graph can contain only approved build content; consumer access additionally
requires the matching PostgreSQL PUBLISHED version. No cross-database atomicity
or exactly-once guarantee is claimed. Failed/incomplete preparations remain
recoverable and cannot replace the old published head or leak through consumers.
Concurrent head changes require an explicit new supported request. Projections
are rebuildable from approved PostgreSQL data and never independently accept facts.

Use the specified BAAI/bge-small-en-v1.5 at immutable revision
5c38ec7c405ec4b44b94cc5a9bb96e735b38267a. Its published ONNX artifact permits
native CPU inference with the already pinned onnxruntime1.30.0/tokenizers0.23.2,
CLS pooling and normalization; no duplicate embedding framework or GPU dependency.
Add neo4j6.4.0 driver for the existing loopback server. Record exact dependencies,
licenses, model hashes and tested inventories before activation. Keep original
parser/stage environments unchanged. Model weights/caches remain ignored.

Chunk only approved exact support, retaining observation/evidence IDs and source
offsets. Measure tokens with the actual frozen tokenizer, including special
tokens/headers. Aim below450tokens and enforce512tokens with no silent truncation.
Long exact text is split with checked Unicode offsets; retain full support in the
observation. Store384-dimensional finite normalized vectors and lexical postings
at the same corpus version. Retrieval ranking/Q&A remains M1.11; no effectiveness
claim follows from constructing an index.

## Verification and checkpoint

Test supported positives and controlled-invalid inputs, stale reviews/configs/
dependencies/actors, exact context and Decimal preservation, immutable histories,
scoped effects/conflicts/cycles, as-of missing dates, publication rollback/head
concurrency, projection outage/recovery/rebuild and consumer version isolation.
Run disposable PostgreSQL tests before new migrations touch primary data. Use
only scoped disposable graph data for engineering tests; preserve existing nodes.
Verify an authenticated real-source publication using the original evidence and
review, with all original records unchanged and measured limitations explicit.
Complete relevant local/hosted checks, record exact IDs/hashes/results and update
CURRENT_STATE/handoff before normal verified commits/pushes to existing main.

Primary implementation references: [Neo4j managed transactions](https://neo4j.com/docs/python-manual/current/transactions/),
[driver compatibility](https://neo4j.com/docs/python-manual/current/install/),
[BGE model card and ONNX/CLS guidance](https://huggingface.co/BAAI/bge-small-en-v1.5),
[ONNX Runtime inference API](https://onnxruntime.ai/docs/api/python/api_summary.html).
These are implementation references, not measured project outcomes.

## Operating the implemented draft

Native setup and CI select `--extra entities --extra publication`. Acquire the
five immutable BGE files separately; bootstrap and CI do not download weights:

```powershell
.\backend\.venv\Scripts\python.exe scripts/acquire-embedding-model.py
```

The target is ignored `models/bge-small-en-v1.5`, approximately134MB. Its verified
canonical manifest is recorded in `data/embedding-model-manifest.json` and the
dependency register. When this directory exists, `regintel-api` verifies the
assets and configures the existing loopback graph credentials from the selected
project `.env`. Missing assets keep publication unconfigured; invalid partial
assets fail configured API startup with a sanitized message. No new environment
variable, hosted service, paid call or worker rebuild is required.

The draft adds migration0011; do not apply it to an existing primary database
until the disposable regression passes. Applied0001–0010 remain frozen.
Authenticated administrator endpoints are:

- `POST /v1/admin/publication/builds`: immutable reviewed selection/lineage/effect request.
- `GET /v1/admin/publication/builds/{id}`: approved build and exact audits.
- `POST /v1/admin/publication/builds/{id}/publish`: recoverable preparation/fresh final gate.
- `POST /v1/admin/publication/builds/{id}/rebuild`: audited vector rows and scoped graph reconstruction.

`GET /v1/corpora/{id}` returns an authenticated PUBLISHED active view, with
optional `historical=true` or supported `as_of_date=YYYY-MM-DD`. The response
metadata retains this exact corpus ID. BUILDING versions fail. Unknown source
or effect dates return `TEMPORAL_SUPPORT_UNAVAILABLE` with no observations.
Company/fact/graph consumer APIs and learner source access remain M1.10 work;
the existing exact evidence/original-PDF endpoints retain administrator access.

Projection preparation can be retried without accepting observations twice.
Already-published versions replay their immutable result after code updates.
The v1 projection shapes must remain interpretable when future versions are added.
SQL independently binds complete acceptance/source/context, scoped effects,
immutable history, acyclic lineage, projection coverage and final authority.
Approved build data may be prepared in Neo4j; application consumers must first
resolve the matching PostgreSQL published version and its active/as-of IDs.

Final local/full database/real-source/hosted verification is in progress. No
primary0011 application or real corpus publication is claimed at this checkpoint.
