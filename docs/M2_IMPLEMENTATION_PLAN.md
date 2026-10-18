# M2 — Analysis and Comparison

Authorized on 17 October 2026. Base: `236c03f1af095fecced96deaf3ef80afed8b836c`.
Implementation lives on `codex/m2-comparison`, in a separate checkout while M1
is being tested. Follow the build document's company/profile → evidence viewer
→ metric normalization → formulas → comparison → evaluation sequence. These are
implementation tasks, not invented numbered specification subphases.

## Consumer contract

Reuse M1's published PostgreSQL manifest, frozen accepted entity/metric catalog,
active/as-of view, company facts/graph and exact source viewer. M2 never writes
facts or chooses an observation by timestamp. Compare 2–4 published companies
and 1–12 explicit metric IDs at one complete period and known reporting basis.
Metric labels are presentation only: they do not establish semantic equivalence.
Historical observations stay accessible through M1; arithmetic uses active views.

`POST /v1/compare` is authenticated and pinned to a published corpus version.
Return the requested period/basis, all relevant input facts with immutable
provenance, per-cell availability/context/conflict warnings, normalized values
and explicit pairwise derivations against the first selected company. Missing,
unknown, contradictory or incompatible inputs produce no calculated result.
An unresolved active period/basis that could match the selection blocks arithmetic,
even if another input has complete context. Complete unrelated periods are excluded
only through explicit supported boundaries. Return at most 100 input observations
and 4,000,000 serialized bytes; exceeding either bound fails without truncation.
Unresolved amendment parents remain visible in warnings.

Normalize explicit supported units with Decimal: INR/USD base currency (rupees,
lakh/lakhs, crore/crores, million/millions, billion/billions), power to MW
(MW/GW), shares and percentages. Never convert currencies. Unknown units,
currency/unit contradictions or incomplete ownership context remain unavailable.
Preserve the original quantity unchanged beside each derived normalization.

The initial transparent formulas are `comparison - baseline` and
`100 * (comparison - baseline) / baseline`. They compare the same metric and
context; they are not growth rates, scores or investment recommendations.
Difference and unit scaling are exact. Percentage difference requires a positive
baseline. Differences between percentage inputs use percentage points, separate
from the relative percentage difference. The latter is explicitly rounded to six
decimal places using ROUND_HALF_EVEN.
Both retain exact input observation IDs; no model or browser arithmetic is used.
Use an isolated Decimal context with adequate precision, exact-operation traps
and the existing 120 integer/120 fractional digit wire limits. Overflow produces
an explicit unavailable result. No new ratios are inferred from metric labels.

`GET /v1/quotes` remains M2-owned. The user explicitly chose to keep quotes
unavailable for now; this decision is recorded on 18 October. Return an honest
typed unavailable response with no prices. No provider, licensing, freshness or
budget policy is configured. Do not introduce an external feed or M4
ledger/snapshot behavior.

## Verification and isolation

Test compatible inputs, different periods/bases/units/currencies, missing values,
conflicts, unknown context, dates/effects, superseded values, Decimal scale and
large/fractional boundaries, formula rounding/non-positive baselines, source IDs,
authentication, malformed requests and sanitized failures. Authored fixtures are
engineering tests, not real financial observations or effectiveness measurements.

Frontend: company profile, explicit comparison selection, full context/warnings,
input evidence inspection, memory-only authentication and cancellation/expiry
clearing. Use a table; avoid charts before numerical corpus coverage exists.
Runtime wire validation must bind corpus, selections and input provenance.

Keep the existing M1 source, ports 8000/5173 and primary corpus unchanged. Local
M2 browser checks use separate loopback ports and their own processes. Preserve
all eleven migrations, frozen M1 algorithms, dependency locks and final specs.
No added dependencies, migrations, model calls or services are planned. Optional
test-only overrides are `REGINTEL_TEST_API_PORT`, `REGINTEL_TEST_WEB_PORT` and
`REGINTEL_TEST_PYTHON`; default CI ports remain 8000/5173. The isolated runtime
proof accepts `--source-project` to read an existing approved local corpus.
Run relevant tests, full regression checks and review before GitHub checkpoints.
Record actual results and remaining real-corpus limitations in CURRENT_STATE.

## Verified checkpoint — 18 October

Source `921e6a616ee27d82eb97362aa90cec3298761a95` is pushed to the isolated M2
branch. Exact-source [CI 39007655529](https://github.com/127yap101/RegIntel/actions/runs/39007655529)
passes Windows/Ubuntu foundation and Linux data infrastructure. Public run/job/
step conclusions verify the complete commands, fresh migrations, authentication
and restart persistence. Raw logs were not accessed; no hosted test counts are
inferred. All 34 source fingerprints match that commit.

Local final-source verification passes 1987 backend tests with six disclosed
Windows platform skips (493 integration cases deselected), 277 frontend unit
tests, all 30 Chromium cases, lint/types/build and static/generated checks.
Four new disposable PostgreSQL cases pass. All 136 selected frozen M1 inputs,
including eleven migrations, remain unchanged; the real read-only proof preserves
all 37 state-table hashes. See `data/analysis-validation-report.json` for the
measured results and disclosed repaired attempts.

Overall M2 acceptance remains open for real numerical inputs and user testing:
the actual published corpus contains one company/narrative and zero numeric
facts. Authored positive tests are engineering verification only. Quotes remain
unavailable by explicit user choice. Preserve the M1 main checkout and its manual
testing ports; do not advance to M3 from fixture success.

Decimal policy reference: [Python 3.12 Decimal documentation](https://docs.python.org/3.12/library/decimal.html).
