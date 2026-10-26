# Numerical review access and module history

26 October 2026. Continue on `codex/m2-comparison`. These additions preserve
existing M1 endpoints and do not change the original laptop corpus or any of
migrations1–18. No dependency, required environment variable, quote provider,
service or public port is added.

## M2: private numerical context review HTTP

The staged context decision now has an administrator HTTP boundary:

| Request | Result |
|---|---|
| `GET /v1/admin/numerical/gates/{gate_id}` | Selected immutable gate, complete exact M1 word/geometry binding, and recorded review or null |
| `POST /v1/admin/numerical/gates/{gate_id}/review` | Explicit immutable context decision through the existing repository |

The request body remains `NumericalContextReviewRequest`: selected `gate_run_id`,
`CONFIRM_CONTEXT` or `REJECT`, complete sorted `evidence_ids`, and a nonblank
`note`. The server supplies the authenticated actor and auth version. Path/body
gate mismatch and conflicting decisions return409. Invalid input returns422;
anonymous/learner access returns401/403; unknown history returns404. Missing or
unverifiable prerequisites are explicit rather than accepted as empty state.

Read packets retain the gate/binding/parse and exact evidence membership, without
serializing the entire retained page bank. Inspection is historical. A new
confirmation still rechecks installed gates, original source bytes, sealed M1
binding and current approval snapshots. All mandatory checks must pass. A note
cannot override unresolved context. Exact retries retain the original decision.

Native API access is opt-in with the additional CLI argument
`--numerical-runtime-file <selected-native-parser-descriptor.json>`. Use the exact
explicitly selected, calibrated native descriptor for the stored numerical inputs;
no descriptor is discovered or manufactured. The ordinary API starts without this
argument and returns503 for this private boundary. A missing/invalid supplied
descriptor fails startup with sanitized diagnostics. Programmatic application
construction can inject `numerical_review_repository` for an explicit owned setup.

This does **not** accept a financial observation or publish a corpus. All decisions
retain `acceptance_eligible=false`, `mandatory_m1_validation_complete=false` and
`publishes_fact=false`. The four retained real gates still require review and
cannot be confirmed. Their original owned proof database was removed; the API
does not seed retained JSON into a live database. Complete the versioned numerical
acceptance/publication adapter before serving these values to M2 comparison.

## M3: selecting a published glossary version

Authenticated learners can call `GET /v1/learning/versions?offset=0&limit=20`.
The bounded page contains published version/parent IDs, reviewed-definition counts
and the current independent glossary head. Drafts and rejected definitions are
absent. Each selected manifest is hash-checked and validated before listing it.
The page and current head share the publication lock, avoiding a mixed snapshot
within one response. History follows recorded parent versions rather than
timestamps or random IDs. An old manifest remains available through the existing
`GET /v1/learning/glossary/{version_id}` endpoint.

In **Financial learning**, sign in and use **Published glossary history** to select
a version. Definitions and contextual explanations keep that glossary version.
Switching version clears the previous definition/disclosure context and PDF view.
An administrator can continue draft/review work, but publication is disabled in a
selected historical view. **Refresh reviewed glossary** returns to the current
head before another publication. Backend parent checks remain authoritative.

An empty published history remains empty. The seven starter drafts stay explicitly
unreviewed; no content approval, metric mapping or publication is seeded.

## M4: inspecting a recorded portfolio prefix

In **Virtual portfolio**, **View balances after order #…** selects the exact
owned account/ledger/analytics prefix through that order. Rejected orders are
also immutable history events. **View opening balance** selects the account ID
and zero orders. The displayed portfolio version is explicit.

Selected history is read-only in the browser. **Refresh portfolio** returns to
the current account before another order. Pending requests must first be resolved
with their original idempotency key. Account reads are checked against the selected
version, and ledger/analytics requests remain pinned to it. Previous/next history
pages preserve that selection.

Quotes and market valuation remain unavailable by user decision. These controls
add no prices, current return claims, cost-basis convention or real execution.
Successful buy/sell scenarios continue to use labelled fixed-price engineering
providers in tests.

## Verification and handoff

Use the existing fresh-clone setup and [module run guide](M3_M4_RUN_AND_TEST.md).
Keep the original M1 manual-test checkout/database separate. Dedicated live checks
create and remove only their own disposable database:

```text
python scripts/check-migrations.py --test-file backend/tests/integration/test_numerical_review_http.py
python scripts/check-migrations.py --test-file backend/tests/integration/test_learning_history_storage.py
```

The optional `--junit-report .cache/<name>.xml` writes a bounded project-local XML
report. On a failure, CI exposes sanitized test class/function names as check
annotations; assertion text, parameter values, tracebacks and captured output are
not copied into those annotations. This improves diagnosis when raw Actions logs
are unavailable. It does not change test assertions, selection or exit status.

Measured results and disclosed limits belong in the checkpoint report and
CURRENT_STATE.md. Engineering tests do not establish independent educational
review, a real numerical approval or held-out research effectiveness.
