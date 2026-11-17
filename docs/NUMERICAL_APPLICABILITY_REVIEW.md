# Numerical source applicability review

Updated 16 November 2026. This implements the source-specific review record required by
the approved numerical producer plan. Cross-page issuer, currency and fiscal
definitions, separate reporting-basis clauses and qualified unit defaults need
explicit applicability to the selected value, row and period column.

## Implemented contract

An authenticated administrator can read the required assertions and record an
immutable `APPLIES` decision. Every request retains the gate ID and input/result
hashes, evidence binding ID, value/row/period cell IDs, all selected page indices
and the complete ordered original-word evidence IDs for each applicable phrase.
The reviewer supplies an explanation after inspecting those pages. Actor and
authentication version come from the current authenticated user.

The requirement builder recognizes supported cross-page captions, explicit
reporting-basis clauses and bounded `unless otherwise specified/stated` unit or
basis defaults. Injection, illustrative language, negation, unsupported qualifiers,
failed checks, missing issuer/metric/policy approvals, unknown quantities and
changed source/context snapshots block submission. The full qualified words
remain part of the evidence binding and review.

Migration `0024_numerical_applicability_reviews.sql` adds an append-only review
table with exact gate/request/actor/phrase/page guards. Concurrent identical
submissions retain one original decision and actor. A changed note or selection
conflicts. Historical reads preserve the recorded configuration and exact source
membership. New submissions recheck original source bytes, current approvals,
sealed parse membership and the installed gate configuration.

## Administrator API

The configured numerical source repository supplies these endpoints.

- `GET /v1/admin/numerical/gates/{gate_id}/applicability/requirements`
- `POST /v1/admin/numerical/gates/{gate_id}/applicability`
- `GET /v1/admin/numerical/gates/{gate_id}/applicability`
- `POST /v1/admin/numerical/gates/{gate_id}/applicability/gate`

Requirements return `eligible`, explicit `blockers` and the complete selection.
To submit an actual review, retain the returned selection, use request schema
`numerical-applicability-request-1`, set `decision` to `APPLIES` and supply the
reviewer's explanation in `note`. The request omits `eligible` and `blockers`.
Anonymous and learner access fail. A path/body gate mismatch or changed evidence
conflicts. Missing configuration returns an unavailable response.

## Gate resolution and administrator workflow

The saved attestation has `acceptance_eligible=false`,
`mandatory_m1_validation_complete=false` and `publishes_fact=false`. Existing
gate state, context confirmation, accepted observations and corpus publication
retain their separate contracts. The explicit gate rerun consumes the stored
attestation in `bound-numerical-applicability-input-1`, retaining the exact original
gate, original actor, full source binding and immutable review. It rechecks the
current source bytes, sealed parse, approved identities/metric/policy and installed
configuration. Only supported applicability checks can change from REVIEW to PASS;
quantity, evidence and already-passing checks remain identical. Legacy input bytes
are unchanged. Migration25 adds a guard to the existing append-only gate table,
requiring the exact persisted base gate and attestation.

The rerun returns `base_gate_run_id`, `applicability_review_id` and a review `packet`.
Success creates a separate READY_FOR_REVIEW gate, with no automatic confirmation,
candidate acceptance or publication. Stale approval/configuration conflicts require
fresh inspection; unverifiable source bytes remain unavailable. Historical reads
retain earlier decisions. A resolved gate still needs explicit context confirmation,
candidate preparation, acceptance and common publication. All qualified original
words remain in the binding used by the acceptance/publication path.

In the administrator numerical panel, open an unresolved gate and choose
**Check applicability requirements and history**. Resolve listed blockers first.
Inspect the target cells and every asserted phrase in the verified original-page
viewer. Confirm applicability, enter a review note and record the decision. If the
response is uncertain, retry the retained exact request. Then choose **Rerun
numerical gates with recorded applicability**. The returned gate opens separately
for context confirmation. Neither checking requirements nor opening evidence saves
a review. These controls never substitute an agent-generated human approval.

## Remaining real acceptance

The four retained real gates still need issuer/metric/policy and applicability
resolution. Actual human review and real M2 expected-result acceptance remain
required. The running installation stays on its recorded schema until a tested
upgrade is performed. Current code requires migrations through25 at startup.

## Verification

The new suites use labelled authored source fixtures and owned disposable
PostgreSQL databases. See CURRENT_STATE.md for completed check counts. Run each
integration file through `scripts/check-migrations.py --test-file` using the
configured project environment. Original source PDFs, generated reports and
database credentials stay in ignored local storage.
