# Numerical review queue implementation

2 November 2026; authorized continuation across M1–M4 from `594d684`.

The numerical administrator currently needs an opaque saved gate ID before
opening a review. Add a private, current-administrator read-only queue at
`GET /v1/admin/numerical/gates`. Search the literal uploaded company name and
filter stored gate state and recorded context-review state. The uploaded name
is intake metadata, not an accepted company identity. Stable gate-ID ordering,
at most 20 records per page, a 10,000 offset bound and an 8 MiB retained-payload
budget keep the read bounded. Empty and unavailable results stay distinct.

Read canonical, hash-verified gate results and recorded reviews with exact
source/parse/context membership. Do not load the potentially 40 MiB complete
gate input for each queue row. The queue is retained history, never fresh
validation, acceptance eligibility or proof of current publication. Opening a
row loads the existing complete review packet and checks that its immutable gate
and source match the selected row. Review, candidate creation, acceptance and
publication continue to perform their existing fresh mandatory checks.

Use separate queue models/repository; do not change the frozen gate/context/
review configuration source files or any migration. Add generated administrator
contracts and an explicit load/refresh/filter/page interface. Preserve direct
ID lookup. Clear old selection/source/notes on navigation, reset decisions to
REJECT and disable queue navigation while a write outcome remains uncertain.
Logout/revocation must clear the private queue and cancel pending reads.

Verify actual owned PostgreSQL/HTTP access, filters, pagination, canonical/hash
and source membership failures, historical decision changes, no writes and
unchanged review/acceptance workflows. Check strict client contracts, hostile
intake labels, selected-source matching, pending-write locks and cancelled reads
in browser/unit checks. Capture declared authored HTTP fixtures, keep real
approval separate, update CURRENT_STATE.md and the measured handoff, then commit
and push the verified checkpoint. No dependency, migration, required setting,
quote source, new service or public port is needed.
