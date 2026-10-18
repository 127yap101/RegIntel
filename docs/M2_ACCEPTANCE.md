# M2 acceptance evaluation

The evaluator reads one explicitly selected PUBLISHED M1 corpus. It compares M2
outputs with independently recorded expected values, availability states and
exact observation/evidence IDs. It never accepts facts, publishes a corpus or
changes projections. The application continues to determine all financial
compatibility and arithmetic.

## Run it

From a normally bootstrapped M2 checkout with the approved local data services:

```powershell
uv run --project backend --locked --no-sync --offline python scripts/evaluate-analysis.py --plan data/analysis-acceptance-plan.json
```

The existing plan pins the actual controlled Premier corpus and deliberately
contains no numerical cases or reviewer claim. The corpus currently has one
company and no numerical facts. Expect `BLOCKED`, zero executed cases and all six
coverage categories missing. This is an incomplete acceptance result.

A clone does not include the database or original PDFs. On another machine,
prepare a plan with that machine's actual published corpus ID and manifest hash
after the M1 workflow. The IDs in the checked-in plan record the existing local
proof; they do not recreate accepted observations or supply missing corpus data.

When using the existing isolated checkout and the original approved local Python
environment on this Windows machine:

```powershell
Set-Location D:\RegIntel\.cache\worktrees\m2-comparison
$env:PYTHONPATH = 'D:\RegIntel\.cache\worktrees\m2-comparison\backend\src;D:\RegIntel\.cache\worktrees\m2-comparison'
& D:\RegIntel\backend\.venv\Scripts\python.exe scripts/evaluate-analysis.py --plan data/analysis-acceptance-plan.json --source-project D:\RegIntel
```

`--source-project` reads the existing approved local `.env`, source storage and
read-only state-snapshot helper. It avoids copying credentials or modifying the
M1 checkout. No API/frontend server is started, so M1's ports remain available.
Use the normal locked setup in a teammate's own clone; these machine-specific
paths are not portable prerequisites.

Print the complete plan schema without connecting to a database:

```powershell
uv run --project backend --locked --no-sync --offline python scripts/evaluate-analysis.py --schema
```

## Prepare reviewed cases

Use published M1 input observations and exact source/context evidence to prepare
the plan. Any new observations must first follow M1's own ingestion, gates,
review and publication workflow. M2 cannot populate missing authoritative facts.
Keep the current main corpus unchanged while it is being manually tested.

Pin `corpus_version_id`, its exact `manifest_sha256` and
`calculation_policy_version`. Every case carries its own complete comparison
request under that same corpus. Select explicit canonical company/metric IDs,
complete financial periods and known reporting bases.

For each selected metric, independently record every selected company's state,
normalized value/unit/currency/multiplier, ordered input observation IDs and the
sorted distinct evidence IDs from both input supports and context witnesses.
Record every baseline comparison, including its exact input observation IDs,
difference, unit/currency, percentage state and rounded percentage difference.
Financial values in the plan are decimal strings. Unavailable values are null.
The first selected company remains the baseline.

Calculate/check expected amounts independently of the production comparison
function. Review the raw units, periods, basis and exact evidence rather than
copying the output being tested. The evaluator does not generate its own oracle.

Each required category needs a matching case with actual supporting input context:

| Category | Coverage requirement |
|---|---|
| `same_period_compatible` | A supported available baseline comparison. |
| `different_periods` | Incompatible accepted inputs at a different complete period, with the selected basis. |
| `standalone_vs_consolidated` | Incompatible accepted inputs at the selected period and the other known basis. |
| `different_units` | An available comparison across explicitly different supported unit scales. |
| `missing_metric` | A missing company/metric input and an available numerical input. |
| `conflicting_observations` | Multiple accepted active inputs at the same selected period/basis remain a conflict. |

Controlled incompatible selections test abstention; they do not create or change
financial disclosures. A category label alone does not establish coverage.
An empty suite cannot pass, and failing cases never contribute coverage.

Leave `reviewed_by` and `reviewed_on` null until the expectations have actually
been reviewed. Record both together when that happens. Declare `AUTHORED` for
engineering fixtures and `REAL_FILINGS` only for real-filing cases. These labels
are operator assertions; the tool does not verify a reviewer's identity or turn
authored data into gold data. Never enter a fictitious reviewer or research result.

The plan is bounded to 1,000,000 bytes and 24 cases. Standard M2 request/result
bounds still apply; captured support-ID collections are bounded to 100 entries.
Unsupported or oversized cases fail explicitly without truncating evidence.

## Read the report

Each run writes a fresh ignored `.cache/analysis-acceptance-<uuid>/report.json`.
It records the plan hash, selected manifest/policy, actual/expected values and
IDs, category coverage, review status and the actual published numerical
inventory. The existing read-only snapshot checks all 37 authoritative tables
before and after; a changed state fails the run. A concurrent legitimate M1
write can also fail this check, so use a quiet window for the preservation proof.
The evaluator does not contact a model or quote provider.

| CLI exit | Report outcome | Meaning |
|---|---|---|
| 0 | `CASES_PASS` | Every recorded case matches, all six categories are covered and review metadata is present. |
| 1 | `FAIL`, or a sanitized command failure | A case, input, pinned scope or state-preservation check failed. |
| 2 | `BLOCKED` | No cases failed, but review or required coverage is incomplete. |

In PowerShell, inspect `$LASTEXITCODE` for the native exit code. Failed command
diagnostics omit database credentials and internal exception text. Detailed
successful case reports remain local for review.

`CASES_PASS` concerns the recorded cases only. It does not close team acceptance,
establish real-world accuracy, supply a held-out benchmark or replace user
testing. The real-data evaluation and reviewed numerical corpus remain pending.
Quotes stay unavailable by explicit user choice.
