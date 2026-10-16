# M1.11 — Published retrieval and extractive Q&A

Started 15 October from verified M1.10 handoff fba55ff. Sequential implementation,
verification, commits and normal pushes to existing main remain authorized.
The approved Windows/native application and private Linux worker stay in place.

## Scope

Add authenticated POST /v1/retrieval and POST /v1/answers. Resolve one PUBLISHED
PostgreSQL corpus and its active/historical/as-of observation IDs before access.
No BUILDING, unaccepted or unrelated corpus rows enter ranking. Verify the
immutable retrieval bytes against the publication commit, model manifest,
observation membership and actual pgvector/lexical rows in a read-only snapshot.
Use the existing pinned offline BGE encoder, without silent query truncation.

Four controlled arms share corpus, query, top-k, context budget and output policy:
B0 exact pgvector cosine ranking; B1 adds explicit company/period/basis filters;
B2 adds BM25 and RRF with k=60; B3 adds bounded one/two-hop Neo4j relation
expansion and reapplies every filter. Corpus/version/active gates apply even in
B0; B0 reports that experimental metadata filters are not applied. Never relax
filters or silently replace a failed graph arm with another method.

BM25 uses the published exact text and, in B2/B3, approved context witnesses
(including original-text row/period/unit/basis headers) as an inseparable context
bundle. Do not invent table cells, section labels or OCR support. Existing v1
projection bytes and frozen publication code remain unchanged. No new migration,
backend dependency, environment variable, worker build or infrastructure planned.

Bounds: question 1000 characters and actual encoded query at most 512 tokens;
top-k 1–10; context budget 128–4096 actual tokenizer tokens; rank pool 100 per
channel; graph expansion 1–2 hops and at most 1000 distinct relations. Explicit
errors/unavailability on input/projection/graph overflow. Entire observation
support/context bundles fit or are omitted with a disclosed count; never clip
quotes or remove conditions to fit a budget. Exact citation membership/source
checks run before returning selected support.

Default answers are labelled source excerpts, copied from accepted source text
with application-built evidence/span/page/version/hash citations and full
conditions. Ranking alone does not establish an answer. A conservative lexical
topic gate is an engineering abstention rule, not calibrated semantic support or
research effectiveness. Conflicts stay separate. No hosted generation or API cost.

Numeric questions are routed to a deterministic accepted-value lookup requiring
explicit metric/company/complete period/basis/unit/currency context. Preserve
Decimal strings, disclose conflicting/incompatible/missing input and exact
support. Free-text numeric intent without that context returns unavailable;
cross-fact formulas/comparison remain M2-owned, never LLM arithmetic.

Add bounded question/source inspection to the existing corpus-pinned explorer;
reuse memory-only authentication, stale-request cancellation and exact viewer.
Keep configuration/model/policy hashes, request identity, measured timing/token
counts and zero paid-provider usage explicit. No held-out model selection or
effectiveness claim. Original corpus remains one conditional Premier narrative,
zero real relations/numeric positives, absent parent and unsupported date view.

## Verification and closure

Test BM25/RRF ordering/ties, all arm differences, filters before/after expansion,
active/history/as-of isolation, immutable projection drift, exact budgets,
source/citation tampering, unknown/oversized inputs, direction/cycles/graph
outage, prompt text inertness, numeric Decimal/context/conflict cases and current
authentication. Real PostgreSQL/Neo4j checks use disposable authored fixtures.
Run relevant complete backend/frontend/browser/static checks and a read-only real
HTTP/browser proof. Compare original source/processing/publication snapshots.
Record measured metadata, limitations and exact hosted source checks; update
CURRENT_STATE/handoff and publish verified checkpoints. Next is M1.12.

Primary implementation references: [pgvector cosine query](https://github.com/pgvector/pgvector),
[Neo4j bounded paths](https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-paths/).

## Local measured checkpoint — 15 October

Implemented the scoped API, committed projection adapter, fixed query prefix,
BM25 k1=1.2/b=0.75, RRF k=60 and bounded actual Neo4j expansion. Traversal can
follow either endpoint to find evidence, while every returned relation preserves
its original subject→object direction. It traverses only approved relation IDs;
context filters apply before and after expansion. Source/context bundles
are serialized complete observation/citation JSON and counted with the actual
BGE tokenizer. They fit or are omitted explicitly, without clipping qualifiers.

Full native backend: 1902 passed/six disclosed Windows skips,237.79s;482 database
cases deselected at that collection. Ruff 192/mypy 126, PowerShell/Bash syntax and
actionlint pass. Nine final disposable database/Neo4j cases pass 29.22s, including
exact Decimal 1234.50, committed projection gates and a real one/two-hop topology
with filtered-edge/corpus boundaries. The extra topology is explicitly authored
and never accepted into PostgreSQL. Current full database collection is 483.

Earlier complete frontend release passes 238 unit/14 Chromium 35.2s, lint/types/build.
A later combined runner passes backend/static/unit/build but has 12 browser passes
and two five-second PDF-readiness timeouts under eight workers. Failure snapshots
show the source pages rendered just afterward. Local browser workers are now two,
with unchanged assertions/timeouts. Final complete frontend release passes
238 unit/14 Chromium in29.6s, lint/strict types/build.
Strict schema export exposed invalid extra Python bound keywords on nested safe
integers; request-specific validators export standard bounds and reject
booleans. Exact header-role/span fixtures and typed context serialization were
corrected. No validation check was disabled.

Real read-only HTTP proof `.cache/retrieval-runtime-dc4cdce5933b46afb44413160de38507`
passes four arms on the same corpus/question/top-k 5/budget 2048/policy. Each has
one real observation and 1059 actual complete-context tokens. Source page 3/hash/
span 0..272 matches, absent dates abstain, numeric intent requires context,
unsupported topics abstain, tiny budgets omit complete bundles and oversized
encoded questions return 422 without truncation. Actual local timing is recorded
per request in the report; one query per arm is not a benchmark distribution.

Real browser proof `.cache/retrieval-browser-43b794e27fd5474897cd306626aba140`
passes B3→verbatim conditional source→original PDF.js page 3/region,375px layout,
a second numeric question with stale source/claim clearing, logout and no token
storage/credential URLs/browser errors. The real proof found the textarea's
implicit label changed after input; an explicit stable label/id fixes repeat
editing and a browser regression checks it. Screenshots were visually inspected.
Original source/processing/publication/authority snapshots are unchanged. Owned
proof API/Vite processes stopped; original services/worker are preserved.

Only metadata is saved to `data/retrieval-validation-report.json`; source PDFs,
screenshots/generated wire outputs remain ignored. No package/lock/SQL/env/
service/worker/model/paid-call change. Existing services were stopped at resume
and restored from their original named volumes. Neo4j emits notifications
for unused relationship type labels in the tiny pilot; queries succeed and
warnings are not suppressed. Large frontend chunk warning remains disclosed.

Source checkpoint and hosted Windows/Linux/full 483 database verification remain
pending. No real numeric/relation/amendment-pair, gold-set/held-out improvement,
macOS/ARM or fresh real-source-clone result is claimed. Next after closure: M1.12.

Additional primary references: [BGE publisher query instruction](https://huggingface.co/BAAI/bge-small-en-v1.5),
[BM25 authors' review](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf),
[RRF authors' paper](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf).
