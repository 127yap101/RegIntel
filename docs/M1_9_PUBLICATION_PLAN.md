# M1.9 — Amendment-aware publication implementation plan

Started 15 October from verified M1.8 source80f4127/handoff74ab4a1. Sequential
implementation, relevant verification, commits and normal pushes are authorized.
The approved Windows/native API and one private Linux worker placement persist.
This records the approved implementation approach. The measured completion record below distinguishes implemented mechanics, actual publication and remaining research limits.

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
tokens/headers. Aim below 450 tokens and enforce 512tokens with no silent truncation.
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

## Operating the implemented publication stage

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

Migration0011 is applied after successful disposable/hosted regression; primary is1–11, pending[]. Its frozen SHA256 is310b96aec87ff153826cbc0a0edf997becb96a27e487e3624e3c18e2479ad9b6. Applied0001–0010 remain frozen.
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

M1.9 is complete as a bounded engineering stage. Primary0011 apply/replay and
actual Premier publication are verified. Exact-source hosted run38717087117 is
SUCCESS across both foundation platforms and all 469 database cases, auth and
restart persistence. The final local full suite has 468 passes/one storage setup
error; all 7 affected cases pass a fresh retry. No full native 469pass is claimed.
See the measured report and completion record below.

## Reader and operator contracts

An approval request selects at most100 canonical candidate IDs, sorted and
distinct, each with its owning sealed run and explicit original review ID or
null. It supplies no accepted fact, computed gate, embedding or graph payload.
An existing final rejection cannot be ignored by supplying a null review. A
review from an earlier validator stays historically attached to that run;
publication records the independently recomputed current result alongside it.

The pilot bounds historical observations at10,000, active IDs at1,000 and
filing/lineage/effect histories at1,000 each. Exceeding a bound fails explicitly;
no data is truncated. These are bounded engineering contracts, not measured
capacity or throughput. Date-as-of means source availability plus supported
effect timing, independent of the disclosure's financial period. A future
effect cannot activate its child or hide its parent early. Conflicting temporal
effect order requires a new explicit reviewed resolution.

PG BUILDING manifests may be graph/index inputs only after approval. Consumer
code must resolve a requested PUBLISHED PG corpus first, retain its version in
response metadata and filter graph/vector/lexical results using that corpus's
active/as-of observation IDs. The graph's presence alone cannot establish
publication. Ranking, query-prefix handling, B0–B3 and bounded graph expansion
remain M1.11. A retrieval projection retains historical evidence for explicitly
requested historical/as-of filtering; it must never be ranked without this
application filter. Rebuilds use approved immutable stored projections, with an
audited atomic replacement of only the selected corpus's derived rows.


## Measured completion — 15 October

Actual corpus614d7861-3f8f-4d5c-a9e5-d7423c2aba58 publishes one complete conditional
Premier narrative, observation4745db6c-09db-4ee2-bc43-efb8a53c7b6b. Acceptance
84061b52-c95b-4347-897f-00ccb4b20f13 binds the existing original review5c42296e
on older validationf93660f2 and independently fresh validation97ec299b. Original
candidates stay CANDIDATE, and all earlier source/review/workflow hashes remain
unchanged. No review is copied or relabelled as belonging to the newer gate.
Manifest SHA256 is6622925d2516aedd4c04194372c7783983b00b14271a9d7edcb7ff5b65cda58e;
publication configuration SHA256 is978659d063ff827146bca5d4fd393683d5e044f4bcb080e144b61e0f3ac45bb1.

The real projection has one49-token exact passage,384-dimensional normalized CPU
BGE vector and matching lexical postings. Neo4j has4 nodes/3 provenance edges and
zero corporate relation observations. Actual token-bound rejection, lossless
Unicode splitting, repeatable inference, authenticated corpus/evidence reads,
anonymous/learner write denials, two publication replays and graph/vector rebuild
pass. The proof API was stopped after completion. Source-containing manifests
and vectors stay in ignored.cache; metadata is data/publication-validation-report.json.

The actual addendum's referenced parent remains absent. No real lineage/effect,
numeric/relation positive, original table-cell success, OCR success or research
improvement is claimed. Source publication date remains null; date-as-of returns
TEMPORAL_SUPPORT_UNAVAILABLE. The authored two-filing tests prove scoped mechanics
and historical traceability only. Held-out amendment/retrieval evaluation and
fresh real-source clone/macOS/ARM verification remain later work.

The first runtime helper attempt used an incorrect login route and stopped
before any build/authority. It was corrected to the existing OAuth2 token/form
contract with trust_env=False, then the full real proof passed. No product,
validation algorithm or applied migration was changed for this helper repair.
Exact-source21a72f1 hosted run38717087117 passes Ubuntu 1804/one skip,
Windows 1802/three skips,212 frontend/3 Chromium on each, lint/types/build,
Ruff/mypy 108 and 469 live database 377.56s, migrations/auth/restart persistence.
Final 25local publication storage cases pass 128.16s,34 engine/projection and 18 HTTP.
The long full native run records 468 passes and one storage-unavailable setup
error; all 7 affected cases pass fresh retry 10.38s. Cause is unverified. Its full
failure and retry are preserved in the execution log and measured report.
