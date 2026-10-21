# Numerical preparation inspection history

This checkpoint continues the approved [M1 prerequisite for M2](M2_NUMERICAL_PRODUCER_PLAN.md).
It retains exact inputs and results from the [joint-context inspector](M1_NUMERICAL_CONTEXT.md).
The records are preparation history. Every record and result remains
`acceptance_eligible=false` and `mandatory_m1_validation_complete=false`.
They cannot approve context, accept facts or publish a corpus.

## Stored inputs and replay

`NumericalContextStorage.save(draft, user)` requires a current active
administrator. In one repeatable-read transaction it loads sealed original
pages, the actual entity registry, the selected registered metric and numerical
policy. Missing metric/policy approvals remain explicit nulls. It verifies each
distinct original PDF, runs the existing deterministic inspector and retains
canonical input/result bytes with their SHA256 fingerprints.

`NumericalContextRecord` includes the draft, complete inspected pages and
approval snapshots, original filing/blob/hash, inspection configuration,
storage configuration and original submitting administrator/auth version.
The storage configuration fingerprints the three new history modules and
migration 13 separately from the unchanged inspection/preparation code.
Exact input and result budgets are 16 MiB and 1 MiB. Pages remain bounded to four.

An identical save returns the original record and submitting actor. The
deterministic identity binds inspection and storage configuration. Conflicting
identical inserts use `ON CONFLICT DO NOTHING`; repeatable-read serialization
failures and deadlocks retry the complete transaction up to three times. An
exhausted retry returns an explicit unavailable result. New approval snapshots
or configurations produce separate history rather than rewriting a result.

`get(id, user)` checks current administrator access, canonical bytes, fingerprints,
the primary uploaded-source binding and exact sealed-page membership. It returns
the retained approval snapshots. A missing or modified physical PDF blocks a
new save; it does not erase a readable historical record. Historical reads do
not claim that the PDF is still physically available or that an old approval
snapshot is current.

When the retained inspection configuration matches the installed inspector,
the typed record also replays that inspector against its retained inputs.
Different historical configurations are retained without rerunning newer rules
over old results. Hashes identify retained inputs; they are not signatures,
human review or financial acceptance.

## Database guards

Migration `0013_numerical_context.sql` adds only
`numerical_context_records` and `numerical_context_pages`. Insert guards bind
the current administrator, original source, deterministic identities, byte
hashes, exact registry/catalog/policy snapshots, canonical check codes/states
and sealed page payloads. Deferred completeness requires every page link to be
inserted with its parent in the same transaction. Later membership additions,
updates, deletes and truncation are rejected.

These guards protect retained membership, snapshots and preparation scope.
They do not prove all financial semantics or authorize a supported proposal.
Controlled invalid input can be retained as `QUARANTINED`; its quantity stays
null and acceptance remains false.

Use the normal migration loader through 13 only in an independently configured
M2 installation or an owned disposable test database. Preserve the original
M1 checkout and manual-test database at migrations 1–11. Migrations 1–12 are
unchanged. No dependency, public endpoint, frontend flow or required application
environment variable is added.

## Verification and remaining work

The [measured history report](../data/numerical-context-history-validation-report.json)
records actual test results, fingerprints and the real-source disposable proof.
Pure record tests cover identity, exact Decimal JSON, tampering, byte bounds
and historical configuration behavior. Database tests exercise concurrent saves,
new approval snapshots, current permissions, source modification/removal,
cross-version quarantine, immutable membership and direct SQL invalid inputs.

In a clone with its own documented configuration:

```powershell
uv run --project backend --locked --no-sync --offline pytest backend/tests/test_numerical_context.py backend/tests/test_numerical_context_records.py
uv run --project backend --locked --no-sync --offline python scripts/check-migrations.py --test-file backend/tests/integration/test_numerical_context_history.py
```

The real proof retains four inspections from eight existing original pages and
5,699 native words. All four require review. It creates no registry/metric/policy
approvals, complete parses, acceptance audits, facts or published corpus. The
owned database is removed and the original M1 authority is unchanged. This is
engineering verification, not independent gold annotation or research accuracy.

Next connect genuine versioned M1 evidence and current-parse membership to the
mandatory validation, actual review, immutable acceptance and publication path.
Preparation capture IDs cannot substitute for public evidence IDs. The existing
parse artifact requires contiguous source pages; a sparse preparation must not
be relabeled as a complete parse or renumbered source. Real M2 acceptance remains
blocked until supported numerical observations are published and independently
reviewed expectations cover all six acceptance categories. Quotes remain
unavailable by the user's choice.
