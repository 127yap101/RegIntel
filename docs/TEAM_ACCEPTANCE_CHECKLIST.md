# Team acceptance checklist for M1–M4

Prepared 28 October 2026; updated 2 November 2026. The user reported an approximate
7–10 day submission window on 27 October. Use `codex/m2-comparison`; `main` retains the earlier M1
manual-testing checkout. This checklist records work to do, not completed review
or module acceptance. No reviewer, approval or gold label is assigned by this file.

Start with [teammate setup](M1_TEAM_TESTING.md) and
[M3/M4 setup and testing](M3_M4_RUN_AND_TEST.md). A clone contains source code,
not the original PDFs, database or credentials. Generate local accounts and use
that machine's actual IDs. Source URLs and expected PDF hashes are recorded in
[the source packet](../data/analysis-source-review.json); verify downloaded bytes
against those hashes. Older intake-status fields are historical snapshots; use
[current state](../CURRENT_STATE.md) for the latest implementation status.

## M1 / Parth: review the four numerical source candidates

These are **unaccepted review candidates**, not published financial facts.
Both source packets concern revenue from operations. The proposed unit is INR
million, but unit/policy/applicability checks remain unresolved. Physical PDF
pages below are one-based; their printed page labels differ.

| Source | Physical table page | Year-end shown | Unaccepted raw value | Retained gate ID |
|---|---:|---|---|---|
| Premier Energies prospectus | 30 | 2024-03-31 | 31,437.93 | c9ffe89e-6241-449f-9fbd-1d0915d27eed |
| Premier Energies prospectus | 30 | 2023-03-31 | 14,285.34 | 3d4cbb7c-d4fc-496f-849a-6418ec007246 |
| Waaree Energies prospectus | 99 | 2023-03-31 | 67,508.73 | 3586d22a-0569-4581-b59b-c96d8d16ce13 |
| Waaree Energies prospectus | 99 | 2024-03-31 | 1,13,976.09 | 4ed77956-205f-4c79-903d-ce286f28e42f |

For each candidate, inspect the original row/value/column together. Record the
issuer/CIN evidence, metric meaning, complete unit/currency header, reporting
basis and the exact applicable fiscal definition. A year-end alone does not
establish the duration start. Check qualifications and whether a definition on
another page applies to this table; a page citation alone does not prove this.

The retained context checks need issuer registry, metric/policy, unit,
cross-page applicability and qualified-language resolution for both companies;
Waaree also needs basis resolution. Each Premier input retains 120 word evidence
IDs; each Waaree input retains 133. Do not replace them with one combined quote.
Return corrections and source-supported review notes. Uncertain items remain
unresolved; this worksheet cannot authorize an override or publication.

The current private [publication-input preparation](NUMERICAL_PUBLICATION_INPUT.md)
returns `BLOCKED` for all four. Retained IDs identify saved engineering inputs;
they do not create records in a teammate's fresh database. The
[unified publication path](UNIFIED_NUMERICAL_PUBLICATION.md) now supports explicitly
accepted numerical candidates. These four unresolved inputs still need actual
source/context approval before they can use it.

The [stored numerical check queue](NUMERICAL_REVIEW_QUEUE.md) now finds records
from that installation by literal uploaded company label and recorded gate/review
state. Open a result to inspect its full original evidence; a ready historical
label does not establish current eligibility. Empty results do not create the
retained laptop records in a fresh clone. Source intake, genuine approval and
the existing mandatory checks still precede acceptance/publication.

## M2 / Yash: check the real comparison acceptance cases

Use [the acceptance guide](M2_ACCEPTANCE.md). Once M1 genuinely publishes supported
numerical inputs, independently record expected values, periods, bases, units and
exact observation/evidence IDs for six categories: compatible same-period,
different periods, standalone/consolidated, different units, missing metric and
conflicting observations. Keep authored fixture results separate from real cases.

The checked-in real acceptance plan is still empty/blocked. Do not fill it with
the raw values above before the producer completes acceptance/publication. Check
that switching corpora clears old comparison results and that unavailable or
incompatible data does not produce a calculation.

## M3 / Shreya: review the seven learning drafts

Use [the starter sources](M3_STARTER_DRAFT_SOURCES.md) and
[the learning workflow](M3_M4_RUN_AND_TEST.md#m3-reviewed-learning).
For every draft, check the linked source, wording, applicability to the intended
Indian filing context, hypothetical example and any proposed M1 metric mapping.
Record corrections or a review note for each term. The examples are educational
inputs, not company facts. Source links alone do not establish approval.

Save, review and publish are separate explicit actions in the administrator
workflow. Verify that learners see only a selected reviewed glossary version;
switching versions clears old context and source selection. All seven starters
remain unreviewed until actual supported decisions are recorded.

## M4 / Artham: check account, retry and history behavior

Use [the portfolio workflow](M3_M4_RUN_AND_TEST.md#m4-virtual-account-and-immutable-outcomes).
Check opening cash, account ownership, current/history versions, holdings,
ledger entries and analytics. A pending order retry must keep the original
request key, company, quantity and filing corpus after reload, without duplicate
execution. Another user's portfolio/history must remain inaccessible.

Quotes remain unavailable by the user's decision. An ordinary interactive order
should record `QUOTES_UNAVAILABLE` and leave cash/holdings unchanged. Successful
buy/partial-sell/final-sell, insufficient cash, oversell and concurrent/retry/replay
cases use labelled fixed-price automated fixtures in
[the engine tests](../backend/tests/test_portfolio_engine.py) and
[database tests](../backend/tests/integration/test_portfolio_storage.py).
Those prices are engineering data. A reviewed runtime price dataset/provider is
still needed before a successful interactive trading demonstration; none is
enabled by this checklist. Market valuation and remaining analytics limitations
must stay visible.

The [FIFO analytics guide](PORTFOLIO_FIFO_ANALYTICS.md) adds an independently
specified fixed-price acceptance example. Check partial sales, losses, final
closure and reopening against its allocated cost, remaining cost and realized
result. Realized sold-share results differ from cash flow while shares remain;
remaining purchase cost is not market value. Selected history versions must
retain their exact amounts after later orders, and a response with inconsistent
cash/holdings must not display financial totals. Quote/source details must show
the original committed inputs. These tests do not configure a runtime provider.

## Report findings and finish evaluation

For a bug, send the branch/commit, module, steps, expected versus actual behavior,
and a screenshot or relevant error text. Include corpus/glossary/portfolio IDs
when relevant; do not share passwords, tokens or `.env` files.

The team must also check reviewed real-filing labels and expected calculations
for the [evaluation plan](04_EVALUATION_PLAN_FINAL.md), then reproduce setup/demo
from a fresh clone. Current engineering test counts do not establish research
accuracy, amendment effectiveness or full project completion. Numerical
administration, native amendment support and the common publication path
now have engineering implementations. Genuine numerical source/context approval,
real amendment-pair acceptance, reviewed learning content and real-data evaluation
remain outstanding. The agent can continue acceptance/handoff implementation
while the team inspects sources and tests the existing workflows.
