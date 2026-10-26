# Concurrent numerical context reviews

26 October 2026. This is a focused correctness fix after module checkpoint
`987cd8c`, within the approved numerical producer integration. It preserves M1
public interfaces, existing data, all eighteen migrations and M3/M4 behavior.

## Observed failure

[CI40290171823](https://github.com/127yap101/RegIntel/actions/runs/40290171823)
passed both foundation jobs, but its Linux database job reported
`test_concurrent_identical_reviews_retain_one_exact_original_decision` as failing.
The new JUnit annotation identified the test; raw CI assertion logs remain
unavailable.

A controlled baseline reproduction aligned two requests after their fresh checks.
It failed with PostgreSQL SQLSTATE `23505` on
`numerical_context_reviews_pkey`. Both requests can observe no existing review and
derive the same immutable ID. The insert handles a conflict on `gate_run_id`,
while the table also has a unique primary key. The overlapping insert can fail on
that other constraint. The baseline probe records only SQLSTATE and constraint
identity; it is an ignored test aid, not product behavior. A separate ordinary
Linux baseline invocation passed once, demonstrating that scheduling matters.
The observed CI test and controlled reproduction support the diagnosis; the raw
CI exception itself was not retrieved.

## Transaction behavior

`NumericalContextReviewRepository` acquires a transaction advisory lock scoped to
the selected gate before its immutable-decision lookup and fresh validation.
Simultaneous submissions for that gate therefore observe one ordered decision:

- An identical request returns the original review, actor and configuration.
- A different decision, note or evidence membership conflicts.
- A gate with no stored decision still requires current administrator access,
  complete exact evidence and all existing fresh source/configuration/approval
  checks. Unresolved context cannot be confirmed.

The existing approval-table locks, immutable insert guards, conflict checks and
bounded transaction retries remain in force. Different gates have distinct lock
keys. The existing implementation fingerprint changes for new reviews; retained
historical reviews keep their original ID and configuration. No accepted fact or
corpus is written. Decisions remain acceptance-ineligible and non-publishing.

## Verification and remaining work

Storage checks cover simultaneous identical requests, retries from different
administrators, conflicting decisions, historical configuration replay, current
authorization, tampering, immutable rows and rollback. Authenticated HTTP checks
exercise the same repository boundary. Record actual native/Linux outcomes and
the containing commit's own CI in the measured report and CURRENT_STATE.md.

This fix does not complete the numerical acceptance/publication adapter, create
real filing approvals, approve glossary starter content or provide market quotes.
Continue those module prerequisites through the existing reviewed contracts.
