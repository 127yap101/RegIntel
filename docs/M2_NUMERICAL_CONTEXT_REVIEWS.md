# Staged numerical-context review

25 October 2026. This extends the approved numerical producer prerequisite after
`bound-numerical-gate-1`, without changing M1's public interfaces or original data.
It records a context decision; it is not a legacy validation, accepted observation
or corpus publication.

## Decision contract

`NumericalContextReviewRepository.save` takes a gate ID, `CONFIRM_CONTEXT` or
`REJECT`, the complete sorted exact evidence IDs from that gate, and a nonblank
review note. The current authenticated administrator is supplied by the caller;
the request cannot choose its actor or auth version.

Confirmation requires the installed gate configuration, an exact replay of all
source/binding inputs and fourteen passing checks. Current source bytes, sealed
parse membership, issuer registry, metric and policy snapshots must still match.
Approval tables are held in share mode until a new decision commits. Changed
snapshots require another inspection/binding; a review note cannot override an
unresolved unit, period, basis, issuer or other mandatory context check. Explicit
rejection retains the same complete evidence membership.

One immutable final decision is retained per gate. Identical concurrent requests
replay the original decision and actor. A changed decision, note or evidence list
conflicts. Replaying an existing identical decision is a historical read rather
than a new confirmation against changed source state. Historical reads preserve
the original inputs and configuration. Any later acceptance implementation must
perform fresh mandatory validation again.

Every decision retains `acceptance_eligible=false`,
`mandatory_m1_validation_complete=false` and `publishes_fact=false`. Confirmation
does not resolve the separate legacy M1 acceptance/publication contract.

## Storage and use

Migration `0018_numerical_context_reviews.sql` adds only
`regintel.numerical_context_reviews`. Migrations1–17 are frozen. Current-admin,
hash, exact gate/request/result membership and confirmation-state guards run
before insert; update, delete and truncate are rejected. No fact, acceptance-audit
or corpus table is written.

The interface remains programmatic, using an already configured numerical source
repository and authenticated current administrator:

```python
from regintel.numerical.review_models import NumericalContextReviewRequest
from regintel.numerical.review_repository import NumericalContextReviewRepository

request = NumericalContextReviewRequest(
    gate_run_id=gate.result.id,
    decision="CONFIRM_CONTEXT",
    evidence_ids=gate.result.evidence_ids,
    note=actual_review_explanation,
)
reviews = NumericalContextReviewRepository(source)
review = reviews.save(request, user)
assert reviews.get(request.gate_run_id, user) == review
```

Do not substitute a fictional review note or approve the retained real records:
all four still have unresolved gates. The new read-only proof replays those
retained real inputs and confirms each refuses `CONFIRM_CONTEXT`. It records no
new real review and makes no database write. Supported confirmations and explicit
rejections are verified separately using labelled authored PDFs and actual M1
storage in owned disposable databases. Those fixtures are not gold annotations.

Run the dedicated disposable suite with the existing local services:

```powershell
.\backend\.venv\Scripts\python.exe scripts\check-migrations.py --test-file backend/tests/integration/test_numerical_context_review_storage.py
```

Preserve the original laptop database. See the [module run guide](M3_M4_RUN_AND_TEST.md),
[bound gate contract](M2_BOUND_NUMERICAL_GATES.md) and
[measured continuation](../data/review-history-validation-report.json). Complete
the mandatory versioned acceptance adapter and real approval/publication work
before supplying these values to M2 comparisons.
