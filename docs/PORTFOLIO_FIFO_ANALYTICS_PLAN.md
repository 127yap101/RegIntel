# FIFO cost and realized-result analytics

30 October 2026; authorized continuation across M1–M4 from `cbcd5b7`.
That exact predecessor passes Windows/Ubuntu foundation and Linux infrastructure
CI in run 41024128636. Real filing/content review and research acceptance remain
separate outstanding work; no source or review gate is waived here.

Extend M4's existing read-only replay-verified analytics with an explicit **FIFO**
virtual-simulator calculation policy. Executed purchases create lots in immutable
ledger order. Executed sales consume the oldest remaining purchased shares for
that company. Allocate their original committed purchase prices, without division
or averaging. Realized result equals committed sale proceeds minus allocated
purchase cost. Remaining purchase cost equals the exact original cost of the
unsold lots. This is a simulator policy, not a tax/compliance determination.

Use Decimal arithmetic at a controlled precision. Existing whole-share, INR,
two-decimal, zero-fee execution remains unchanged. Rejected orders never create
or consume lots. Closed/reopened positions, multiple lots/companies, partial
sales and losses retain exact amounts. Changing ambient Decimal precision cannot
change the result. Do not use current or inferred prices to revalue old entries.

Require complete immutable ledger replay before deriving any amount. Retain the
selected portfolio prefix, all entry IDs, filing corpora and quote versions.
Expose policy and allocated/remaining cost and realized result per company and
in totals. Check conservation of purchase cost and reconciliation of company /
summary amounts. A closed position's existing cash-flow result must reconcile.
Existing entry/company/byte budgets still return explicit unavailability with
no truncated totals. Old orders and ledger rows are never rewritten.

Update the shared generated contracts, exact client-side amount validation and
the existing analytics view. Distinguish realized results, remaining purchase
cost, cash flow and unavailable market valuation. Runtime quotes remain disabled
as requested. Existing history exposes the committed unit price and expandable
quote/source versions so the cost inputs remain inspectable. No runtime provider,
price dataset, dependency, migration or public port is added. Fixed test prices
remain explicitly labelled engineering data.

Verify independently calculated multiple-lot/partial/final/reopened and rejected
scenarios, low ambient precision, malformed totals and complete-ledger limits.
Use actual owned PostgreSQL/HTTP checks for pinned prefixes, read-only behavior,
ownership and unchanged execution/retries. Check the frontend contracts and
browser display/version/logout behavior. Record actual results and limits in
CURRENT_STATE.md and a measured report before the authorized commit and push.
