# Inspect the actual Premier and Waaree review packets

Use `codex/m2-comparison` and the [current runtime guide](LOCAL_RUNTIME.md).
The laptop uses current code from the integration worktree and the original
installation's credentials, database and source storage. A Git clone does not
include those private records or PDFs; another installation must import its own
verified sources and use the IDs it receives.

## Open the source checks

1. Open `http://127.0.0.1:5173/` and select **Administrator workspace**.
2. Sign in with this installation's existing administrator account.
3. Select **Numerical filings**. In **Uploaded company name contains**, enter
   `Premier` or `Waaree`. Leave **All check states** and **Unreviewed** selected,
   then select **Find numerical checks**.
4. Open a stored check. Compare its raw value, period and source hash with the
   [team checklist](TEAM_ACCEPTANCE_CHECKLIST.md). These are proposals awaiting
   review; a stored result does not approve a financial fact.
5. Expand **All 14 source and context gates** and **Original source words and
   table context**. Select a word in the value, row label, column, unit, issuer
   or contextual phrase to inspect its exact original PDF page and highlight.
6. Record source-supported findings for the unresolved checks. Do not submit
   **Record context decision** merely to test the button: it records an immutable
   decision, and the initial selection is **Reject context**.

Premier's revenue table is on physical PDF page 30; Waaree's is on page 99.
Physical page numbers differ from the printed page labels. Check the complete
row/header context, qualifiers and the applicability of definitions from other
pages. A year-end alone does not establish a duration start.

In the 7 November local check, opening a complete saved packet took 6.0–15.3
seconds; opening its PDF value highlight took 2.2–8.5 seconds. These are four
observations on this laptop, not a latency benchmark. Wait for the current read
to finish before retrying; investigate an explicit error instead of submitting
a review to test whether the page responds.

## Resolve prerequisites before approval

The existing Premier entity can be selected through its registered exact CIN.
Waaree still needs a genuinely reviewed identity, and the revenue metric/policy
needs registration through the existing workflows. Unregistered proposal IDs
are not company or metric approvals. Never copy another machine's IDs.

Resolve the unit, cross-page applicability, source qualifiers and Waaree reporting
basis from actual evidence. Preserve every original word; do not replace the
evidence with a combined quotation. Save a fresh context/gate after current
identity or policy decisions so its new snapshots retain those prerequisites.
Earlier unresolved records remain queryable history.

Only a gate that satisfies the mandatory checks can offer context confirmation.
Context review, candidate acceptance and corpus publication remain separate
actions in the [numerical administrator workflow](NUMERICAL_ADMIN_WORKFLOW.md).
M2 can use the values only after that common publication. M3 content review and
M4's unavailable quote source remain independent work.

## Recover or reproduce

If the source viewer cannot load, first check current API/data-service health
using the runtime guide. Do not upload a replacement PDF or regenerate accounts
as a login workaround. Verify the exact original source hash and storage path.
The [intake guide](NATIVE_SOURCE_INTAKE.md) explains checking and replaying an
explicit retained source plan; repeating it verifies the same sealed source.

The [intake plan](REAL_NUMERICAL_INTAKE_PLAN.md) describes the bounded operation.
The [measured report](../data/real-numerical-intake-validation-report.json) records
actual installation IDs, checks and preservation results. This guide supplies no
human review, gold label, financial acceptance or research-performance result.
