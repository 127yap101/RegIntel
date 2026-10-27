# Numerical publication input preparation

This is the first executable part of the separately versioned numerical
publication adapter. It prepares a complete, inspectable input from the existing
bound gate and actual immutable context review. It creates no accepted fact,
review decision, acceptance audit or corpus. The legacy M1 publication path and
its evidence/span limits remain unchanged.

## Use

Configure the native numerical source repository as described in
[review access](MODULE_HISTORY_AND_REVIEW_ACCESS.md), using the actual selected
runtime descriptor. With a current administrator session, request:

```text
GET /v1/admin/numerical/gates/{gate_id}/publication-input
```

The same read is available programmatically through
`NumericalPublicationInputRepository(source).prepare(gate_id, administrator)`.
Omitting the numerical runtime/repository leaves this endpoint unavailable.
Ordinary M1/API startup keeps its existing behavior.

The repository verifies the current administrator inside a repeatable-read
transaction, rechecks original source bytes, sealed parse and exact evidence,
and compares current registry/metric/policy snapshots. It then reproduces the
installed gate, loads the exact stored context review and evaluates sixteen
ordered categories: source, entity, table context, source scope, attribution,
direction, metric, value, unit, currency, period, basis, denominator, stake kind,
ownership date and extractive review.

This version supports reviewed monetary-duration metrics. Direction and ownership
categories are explicitly inapplicable only for that supported family; this
cannot accept ownership percentages, counts, power or instant-period inputs by
marking their missing context inapplicable. Injection fails the source-scope
check; qualified or unresolved context remains blocked. A review cannot override
those failures.

`BLOCKED` retains the check outcomes and returns no proposed input. Missing
confirmation needs review; an immutable rejection blocks preparation. Changed
approval/source/configuration state requires a fresh inspection/binding/review,
while historical decisions remain readable. Unknown/invalid IDs and absent
configuration return explicit errors. Original-byte conflicts return 409.

`READY_FOR_ADAPTER` includes `numerical-publication-input-1`, preserving the exact
Decimal value and unit, complete financial period/basis, metric/policy, stored
gate/review and full original word/cell binding. All evidence IDs are retained;
words are not combined into fabricated source spans or truncated to sixteen IDs.
The output is a read snapshot, not a write authorization. A future publication
writer must reload and freshly verify its authoritative inputs before commit.

Both states and their proposed input retain `acceptance_eligible=false`,
`mandatory_m1_validation_complete=false` and `publishes_fact=false`. The sixteen
category results describe this preparation; they do not create a legacy
ValidationRun or bypass the still-missing atomic acceptance/publication adapter.

## Verification and remaining work

The measured results are in
[the checkpoint report](../data/numerical-publication-input-validation-report.json).
Positive cases use labelled authored words/PDFs and real PostgreSQL/application
contracts. They are not real financial review or research gold. Separate
read-only replay verifies that all four retained real inputs remain blocked.

Next complete versioned immutable candidate/acceptance persistence, atomic corpus
publication and public evidence-consumer adaptation. Keep the legacy formats and
audits readable, and require genuine source/registry/metric/policy/content review
before publishing real numbers for M2. M3 review, M4 quote-data/analytics work,
research evaluation and fresh-clone handoff remain project work. Quotes stay
unavailable under the user's existing decision.

This step adds one private read endpoint and three internal source modules. It
adds no dependency, migration, required environment variable, service or provider.
Original M1 data, its public interfaces, the manual-test checkout and all eighteen
branch migrations remain preserved.
