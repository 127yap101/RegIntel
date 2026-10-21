# Numerical producer prerequisite for M2

Prepared on 19 October 2026 against M2 source `1840e14` and handoff `792aef1`.
The user explicitly approved this bounded M1 prerequisite extension on
19 October 2026. The finalized specifications remain unchanged. M2 is the active
consumer phase; its real acceptance plan is still empty and `BLOCKED`.
Implementation and verification are recorded separately from this approved plan.

## Verified reason the source packet cannot be accepted

The existing two-document packet in `data/analysis-source-review.json` contains
unaccepted source amounts and page locators, not producer evidence records.
Neither document has been uploaded, parsed or published through M1.

Inspection of the existing code establishes these limitations:

| Producer boundary | Current behavior | Consequence for this packet |
|---|---|---|
| `evidence/projection.py:project_parse` | Persists eligible original text; projected table and cell counts are zero. | Processed table previews cannot become accepted cell evidence. |
| `validation/gate.py:_evaluate` | Server-detected table overlap sets mandatory `TABLE_CONTEXT` to `REVIEW`. | An administrator cannot approve around missing row/header/cell support. |
| `validation/quantity.py:normalize_quantity` | Context is interpreted inside the primary source statement. An end-only duration retains a null start. | A fiscal definition on another page is not joined into a complete period. |
| `validation/gate.py:_numeric_context_scoped` | Requires one complete local subject/metric/value clause with its own context. | Table issuer/metric/header attribution needs an explicit supported producer path. |
| `validation/quantity.py:normalize_quantity` | A currency symbol alone does not establish an ISO currency. | Any currency-definition link also needs exact, applicable source evidence. |

These are code inspection findings. No new Docling benchmark, successful table
parse or numerical gate pass is claimed. The existing maximums are 64 MiB and
2,000 pages; both source files fit those size/page limits, but this does not
establish conversion completion, runtime or quality.

The design already requires joint table/value/context evidence (research method
section 8), multiple evidence records for cross-page support (architecture
section 9), and immutable versioned acceptance. The present bounded text path
does not supply that complete numerical producer slice.

## Approved M1 prerequisite work

1. **Verify original table support.** Use the existing approved Linux parser,
   pinned models and immutable original PDFs. Capture genuine row, column,
   header, value and page geometry. Benchmark the smallest controlled slice
   before expanding processing. Missing or ambiguous original support remains
   unavailable; no concatenated or rewritten PDF is substituted for a source.
2. **Add an explicit evidence/context contract.** Preserve original text and
   table/cell identity, source hashes, page coordinates and exact spans. Link
   the applicable issuer, metric, value, row, period column, unit, currency and
   reporting basis through bounded, typed evidence references. Reuse existing
   contracts where sufficient; version any necessary additions explicitly.
   Processed preview text cannot independently prove a cell or its context.
3. **Validate supported period and context links.** A year-end column and an
   explicit applicable fiscal definition may propose a complete duration only
   through a recorded, deterministic, evidence-backed interpretation. Preserve
   both sources and their applicability. Do not default to 1 April, infer dates
   from a filing date, borrow another column's basis/unit, or waive the old
   unresolved-context gate. Missing/competing definitions continue to block.
4. **Preserve acceptance and history.** Use M1 validation, actual review,
   immutable acceptance and publication. Keep old artifacts, configurations,
   audits and published observations readable. Add a new migration only if
   required; never edit migrations 0001-0011 or reinterpret old records. Do not
   infer lineage or supersession between the existing addendum and prospectus.
5. **Verify before using real data in M2.** Exercise positive and controlled
   invalid row/column swaps, wrong periods/bases/units/currencies, cross-document
   context, unrelated fiscal definitions, transcription errors, injection,
   conflicting observations and immutable history. Then verify the original
   source pages and independently review real expected calculations. Complete
   all six M2 acceptance categories with honest coverage and limitations.

Keep changes in the isolated checkout, using the existing private infrastructure
and owned disposable test databases. Leave `D:/RegIntel`, its current manual-test
corpus and API/frontend ports unchanged. No duplicate service, external quote
provider, paid model call, extra company, dependency or system installation is
proposed. A parser/configuration change needs a new recorded benchmark and
identity; existing processing fingerprints must not be silently replaced.

## Independent M2 verification

Extend the existing PostgreSQL acceptance verification to exercise the complete
six-category authored suite through actual M1 gates/publication and the M2
consumer interface. Expected numbers must be authored independently; source and
observation IDs must come from actual persisted records. Confirm wrong oracles
fail, absent review blocks, conflicts survive, and evaluation leaves state
unchanged. This is engineering verification only, with no fabricated real
filings, human review, primary publication or research result.

`AGENTS.md` requires implementing only the requested phase and explicit approval
for major architecture changes. The user approved this exact prerequisite scope
through the in-chat approval question on19October. Do not ask for that same
approval again. Preserve the isolated-checkout and immutable-history constraints.

## First implementation checkpoint

`regintel.numerical.source_pages` and `scripts/probe-numerical-page.py` retain
word-level original text/rectangles from one explicitly requested source page,
with source/configuration/raw-data/code hashes and original page geometry.
A separate preparation schema records proposed table-cell membership, including
ambiguous/unavailable mappings. Native words remain individual source records;
no combined exact span, cell authority or financial interpretation is invented.
Acceptance eligibility is permanently false for this preparation artifact.

This supplies a reproducible foundation for steps1-2. Complete table/context
evidence persistence, supported period/issuer/currency/basis links, mandatory
validation/review and real publication remain work under the approved plan.
See `docs/M1_NUMERICAL_SOURCE_PAGES.md` for commands and explicit limits.

## Page/word persistence checkpoint, 20 October

The producer library now seals a page preparation and every original word in
append-only PostgreSQL records tied to the existing uploaded source version.
New migration 12 adds two preparation tables; migrations 1–11 and the original
M1 database remain unchanged. Current-administrator checks, exact source/config/
code hashes, deterministic replay identities, atomic completeness and database
immutability protect those records. Native exact word references expose the
original word envelope, including for a quoted substring, and remain ineligible
for acceptance.

The real disposable proof stores four original table/context pages and 2,463
words, verifies replay and the four target word rectangles, and creates no parse,
accepted observation or corpus version. This advances step2's persistence
foundation. Explicit joint cell/issuer/metric/period/unit/currency/basis evidence,
supported duration interpretation, numerical gates, actual review, publication
and real M2 acceptance are still unfinished. The measured persistence report
records verification separately; these results do not establish financial
correctness or research effectiveness.

## Joint-context inspection checkpoint, 20 October

The internal producer now links bounded whole-word references for value/row/
period cells and issuer/caption/unit/currency/fiscal/basis context. Its read-only
administrator repository loads actual registry/catalog/policy snapshots and
re-verifies the original PDF. Eleven deterministic checks retain source and
table membership, exact words, direction of row/column support and explicitly
supported annual boundaries. Missing approvals, ambiguous geometry and all
cross-page applicability remain reviewable; invalid support is quarantined.

This advances steps2-3 as preparation only. Every result remains permanently
ineligible for acceptance. There is no new public evidence contract, persisted
context audit, current-parse adaptation, review, acceptance or publication flow.
See `docs/M1_NUMERICAL_CONTEXT.md` and the separately measured context report.
The next producer work must connect genuine versioned evidence to the mandatory
M1 path before real M2 inputs can be accepted. Preserve the original M1 checkout,
database and frozen specifications.

## Preparation inspection history checkpoint, 21 October

The new history repository retains exact inspection inputs/results, actual
registry/catalog/policy snapshots and original submission in two append-only
tables added by migration 13. Identical and concurrent saves replay the original
record. Changed snapshots retain separate history; current administrator access,
source verification on save, immutable page membership and byte fingerprints
are enforced. Migrations 1–12 and the original M1 database remain unchanged.

This advances step4's preparation-history foundation without accepting a fact.
The four real source inspections still require review. No complete parse,
public evidence identity, mandatory validation, actual review or publication
path is supplied by these records. See [the history contract](M1_NUMERICAL_CONTEXT_HISTORY.md)
and its separately measured report. Genuine versioned M1 evidence and current
parse membership remain the next implementation boundary under the existing
approval; do not fabricate a complete parse from sparse preparation pages.
