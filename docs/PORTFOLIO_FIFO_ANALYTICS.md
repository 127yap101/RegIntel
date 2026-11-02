# Virtual portfolio FIFO analytics

Updated 2 November 2026. This extends the existing read-only M4 analytics on
`codex/m2-comparison`. M1 source/review/publication rules, M2 comparison and M3
reviewed learning keep their own contracts and versions. No migration,
dependency, required environment variable or runtime quote source is added.

## What the amounts mean

Analytics first replay the complete selected immutable ledger and verify its cash
and holdings against the selected account. Executed purchases form lots in ledger
sequence order. Executed sales consume the oldest remaining shares for that
company. This explicit **FIFO** policy belongs to the virtual simulator; it is
not a tax or accounting-compliance determination.

- **Cost allocated to sold shares** (`realized_cost_basis`) is the original
  committed purchase cost of shares consumed by sales.
- **Remaining purchase cost** (`remaining_cost_basis`) is the original cost of
  unsold lots. It is not their current market value.
- **Realized result** (`realized_result`) is committed sale proceeds minus the
  purchase cost allocated to those sold shares. It can be negative.
- **Net virtual cash flow** remains sale proceeds minus all purchase spending.
  It differs from the realized result while purchased shares remain.

Amounts are cumulative through the selected portfolio version. Selling every
share makes the existing closed-position result equal the realized result.
Reopening the position keeps prior realized results and begins new remaining
lots; its closed-position result becomes unavailable until no shares remain.
Rejected orders never create or consume lots. Companies have separate lot queues.

The backend uses `Decimal` with a local precision of 512, whole shares and exact
committed two-decimal INR prices. Allocation needs multiplication and subtraction,
not division, averaging or rounding. JSON carries decimal strings. The browser
checks their exact currency amounts using integer cents, including amounts above
JavaScript's safe floating-point integer range. It does not recompute trades.

## Fixed engineering example

These are authored test prices, not market data. Starting virtual cash is
INR 100000.00 and fees are zero.

| Selected ledger prefix | Shares left | Allocated cost | Remaining cost | Realized result | Net cash flow | Cash |
|---|---:|---:|---:|---:|---:|---:|
| Buy 2 at 10.00 | 2 | 0.00 | 20.00 | 0.00 | -20.00 | 99980.00 |
| Then buy 3 at 20.00 | 5 | 0.00 | 80.00 | 0.00 | -80.00 | 99920.00 |
| Then sell 4 at 30.00 | 1 | 60.00 | 20.00 | 60.00 | 40.00 | 100040.00 |
| Then sell 1 at 15.00 | 0 | 80.00 | 0.00 | 55.00 | 55.00 | 100055.00 |
| Then buy 2 at 7.00 | 2 | 80.00 | 14.00 | 55.00 | 41.00 | 100041.00 |

The partial sale consumes both shares bought at 10.00 and two shares bought at
20.00: allocated cost is 20.00 + 40.00 = 60.00. Sale proceeds are 120.00, so its
realized result is 60.00. Remaining purchase cost is 20.00. A later sale at 15.00
realizes a further loss of 5.00, leaving cumulative realized result 55.00.

## API and browser checks

`GET /v1/portfolio/analytics?portfolio_version_id=<owned-version>` retains its
existing ownership and selected-prefix behavior. `cost_basis_method` is explicitly
`FIFO`. The three amount fields above are required in an available summary and
each company row. Account, analytics and paginated history must use the same
owned portfolio version. Update backend and frontend together; bootstrap/check
runners regenerate ignored schemas and types from Python.

Purchase costs must reconcile to all purchase spending; realized results must
reconcile to proceeds and allocated cost. Each company appears once in canonical
order and company amounts sum to the summary. The browser also rejects a
self-consistent analytics response whose account ID, version, order count, cash
or remaining holdings disagree with the selected account. Selecting a different
prefix clears the previous analytics while the selected response loads.

In **Virtual portfolio**, inspect **Ledger cash-flow analytics**. Its company
table scrolls within the panel on a narrow screen. **Immutable virtual history**
shows the executed unit price and expandable **Quote and source versions**:
source label/kind, snapshot ID, quote version, filing corpus and observation time.
These are the committed inputs, not a fresh price lookup. The ledger and quote
records are not rewritten by analytics reads or retries.

The existing 10,000-entry, 1,000-company and 32 MiB entry-byte budgets still return
`LEDGER_BUDGET_EXCEEDED` without partial financial totals. Cash and paginated
history remain available. Current market value, total market-based value,
unrealized results and returns remain unavailable without supported prices.

## Reproduce the engineering scenarios

Follow [the module run/test guide](M3_M4_RUN_AND_TEST.md) for a fresh clone,
local credentials and the existing data services. Run these in that clone:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml backend/tests/test_portfolio_engine.py backend/tests/test_portfolio_analytics.py backend/tests/test_portfolio_fifo_wire.py
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py --test-file backend/tests/integration/test_portfolio_fifo_storage.py
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py --test-file backend/tests/integration/test_portfolio_storage.py
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py --test-file backend/tests/integration/test_portfolio_history_storage.py
pnpm --dir frontend exec vitest run src/modules/analyticsAmounts.test.ts
pnpm --dir frontend exec playwright test tests/e2e/learning-portfolio.spec.ts --workers=1
```

The database runner creates and removes only its own disposable test database.
The FIFO suite captures actual authenticated HTTP responses for six prefixes;
the checked-in authored fixture round-trips all 18 account/ledger/analytics JSON
contracts. Browser scenarios replay that capture and test a corrupted response.
Independent amount tests include losses, interleaved companies, rejected orders
and a one-cent result above the floating-point safe range. These are engineering
checks; they do not validate real price data or investment performance.

Runtime quotes remain unavailable by the user's decision. A normal interactive
order still records `QUOTES_UNAVAILABLE` without financial movement. This work
does not enable successful runtime trades or bypass real filing/content review.
See [the measured report](../data/portfolio-fifo-validation-report.json),
[current state](../CURRENT_STATE.md) and
[the team acceptance checklist](TEAM_ACCEPTANCE_CHECKLIST.md) for actual checks
and outstanding work across all four modules.
