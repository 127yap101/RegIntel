# M1.6 — Bounded source-linked candidate extraction

This stage adds raw proposals to the existing sealed parse/entity pipeline. It
does not accept financial facts, resolve amendments or publish a corpus. M1.7
must apply semantic/context gates and reviewed decisions before acceptance.

## Implemented path

An administrator registers an immutable extraction metric (`id`, key, label,
numeric/narrative kind and literal cue phrases), then selects a sealed M1.5
entity run and explicit metric IDs. There is no default financial metric
catalogue. Metric definitions describe extraction cues; M2 compatibility,
normalization, formulas and financial definitions remain later work.

The application reloads the complete original-text evidence, entity run,
registered metrics and all current entity-review decisions. A resolving review
can bind an existing proposal; rejection suppresses the mention. Unknown and
unreviewed fuzzy matches supply no canonical identity. Later entity reviews
produce a separate input hash/run; historical candidate runs remain immutable.

The deterministic baseline proposes six directed relation types from explicit
local triggers, numeric facts from a literal cue and its immediately following
raw value, and narrative facts as exact source statements. An unresolved
intervening counterparty blocks endpoint pairing. Co-occurrence, pronouns,
issuer inference, cross-block joins and processed table previews are excluded
from this baseline. It fails explicit input/window/candidate/issue limits
instead of returning an undisclosed partial result.

Each proposal retains effective entity/mention IDs and absolute Unicode
subspans (`evidence_id`, start, end, exact quote). The primary text is one
original-text statement; all endpoint/context spans must lie within it. Raw
values, units, currency labels, periods, basis, denominator, stake kind and
ownership-date text retain exact spans when unambiguous. Dash/blank or a date
cannot be selected as a numeric value. Ambiguous labels stay unknown with an
issue. Negation, attribution, conditions and qualifiers remain in source text.

Stored quantitative rows deliberately keep normalized value/unit/currency and
interpreted dates null, and period/basis `UNKNOWN`. Raw ownership-date text
remains in the draft bundle. No floating-point financial calculation occurs.
M1.7 must establish numeric syntax, exact semantic support, direction and all
required value/context compatibility; exact-source membership alone cannot
establish those properties.

## Authority and storage

Append migration `0007_candidates.sql`; never edit applied0001–0006. New metric,
run and membership tables are immutable, with administrator/auth-version audit,
byte hashes, deterministic application IDs, frozen reviews, known definitions,
exact source geometry/spans and complete same-transaction members. Raw numeric
contexts, existing `CANDIDATE` rows and their support links commit atomically.
Identical requests replay the original result. Failure rolls back the stage.

The pre-existing0003 proposal tables retain their original placeholder-insert
contracts. The new API creates only owned sealed-run candidates; M1.7 acceptance
must require that ownership and the frozen extraction audit, excluding bare
placeholder rows. Existing acceptance/observation/corpus insert gates stay
closed, and no Neo4j/pgvector/BM25 projection is written.

Admin-only endpoints:

- `POST /v1/admin/candidates/metrics`: register/replay a metric definition.
- `POST /v1/admin/candidates/runs`: `{entity_run_id, metric_ids}`; run the baseline.
- `GET /v1/admin/candidates/runs/{run_id}`: read its original drafts and records.

Requests cannot submit accepted facts, arbitrary candidates or provider settings.
The native configured API wires this service automatically. Responses use the
shared envelope, parse version, server request ID and `no-store`; corpus remains
null. Learner/anonymous access is denied. Missing migrations/connectivity return
503; invalid support422, conflict409 and missing selected records404. Internal
diagnostics never enter API error messages.

## Provider boundary and remaining model work

`GeminiCandidateAdapter` accepts an explicitly injected asynchronous transport.
It separates fixed instructions from serialized untrusted input, supplies an
ID-constrained JSON schema and validates exact source/ID bindings after decoding.
No browsing, database, publication, arithmetic or trading tools are supplied.
Byte limits, duplicate/deep/malformed JSON, Unicode errors, refusal, timeout,
model identity and optional token/cost metadata are tested with offline mocks.
Audits record actual adapter/validation code, settings, prompt/schema/input/output
hashes, run ID and latency; unavailable usage/cost remains explicitly unknown.

No SDK, credentials, network transport, real model selection, Gemini call or
charge is configured by this checkpoint. Syntax checks on a supplied model ID
do not prove catalogue availability. Live transport/SDK integration and common
tuning-set benchmarking need an explicitly authorized model/API budget. Freeze
the selected real model/settings/SDK and prompt/schema/configuration hashes
before held-out experiments. Offline tests are engineering correctness, not
model accuracy, supported-claim rate or measured real-world cost.

Official provider guidance consulted13October2026: [JSON structured output](https://ai.google.dev/gemini-api/docs/structured-output)
and [system instructions](https://ai.google.dev/gemini-api/docs/text-generation).
Application validation remains mandatory even for schema-conforming output.

## Verification and reproduction

Run `scripts/run-checks.ps1` on the approved Windows host or
`scripts/run-checks.sh` on the supported shell. Both include the new runtime
helper in lint/type checks. `scripts/check-migrations.py` applies all migrations
and checks live contracts in a freshly generated disposable database, retaining
the existing primary database and volumes.

`data/candidate-probe-metric.json` is an explicit engineering probe definition
for the conditional proposed-public-issue disclosure in the controlled Premier
source. It is not a financial ontology or research annotation. After0007 is
verified/applied and the configured loopback API is running:

```powershell
.\backend\.venv\Scripts\python.exe scripts/check-candidate-runtime.py `
  --api-base http://127.0.0.1:8000 --entity-run-id YOUR_LOCAL_SEALED_ENTITY_RUN_ID
```

The helper verifies the unchanged original PDF/hash and sealed source, registers
the explicit metric, persists/replays the run, reads exact evidence, checks
permissions and preserves earlier sources/jobs/entities/financial authority.
It saves source-containing proof files only under ignored `.cache/`. Teammates
must acquire ignored assets, apply verified migrations, generate their own
credentials and use their actual local parse/entity IDs; this machine's IDs are
not portable database contents. The tracked validation report records measured
results and limitations after verification, never anticipated outcomes.

M1.7 context/semantic gates and reviewer acceptance, M1.8 worker-stage recovery,
M1.9 amendment/publication and subsequent experiences remain unimplemented.

Measured14October closure:1378backend/6Windows skips,312liveDB (104new stagecases),212frontend/3Chromium, lint/types/build, Ruff126/mypy80 and Linux-platform mypy67 pass. Primary1–7 applied, nonepending;0007SHA5385dfda7247aed38dfc152e687a8c5535019e23878a8cc6463ae13b9158f48e. ActualPremier proof stores/replays one conditional narrative proposal; earlier snapshots unchanged, unownedcandidates0 and authoritycounts0. Full measured metadata is in `data/candidate-validation-report.json`. No live provider or research outcome is claimed.
