# Numerical source applicability review

12 November 2026. This implements the source-specific review record required by
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

Requirements return `eligible`, explicit `blockers` and the complete selection.
To submit an actual review, retain the returned selection, use request schema
`numerical-applicability-request-1`, set `decision` to `APPLIES` and supply the
reviewer's explanation in `note`. The request omits `eligible` and `blockers`.
Anonymous and learner access fail. A path/body gate mismatch or changed evidence
conflicts. Missing configuration returns an unavailable response.

## Integration boundary and remaining work

The saved attestation has `acceptance_eligible=false`,
`mandatory_m1_validation_complete=false` and `publishes_fact=false`. Existing
gate state, context confirmation, accepted observations and corpus publication
retain their current contracts. The next implementation must consume this
attestation in a separately versioned gate input, reproduce it against fresh
source/approval state, preserve legacy canonical bytes, and carry the reviewed
qualifications through acceptance and common publication. Administrator UI
controls for this new step also remain pending.

The four retained real gates still need issuer/metric/policy and applicability
resolution. Actual human review and real M2 expected-result acceptance remain
required. The running installation stays on its recorded schema until a tested
upgrade is explicitly performed. Current code requires migration 24 at startup.

## Verification

The new suites use labelled authored source fixtures and owned disposable
PostgreSQL databases. See CURRENT_STATE.md for completed check counts. Run each
integration file through `scripts/check-migrations.py --test-file` using the
configured project environment. Original source PDFs, generated reports and
database credentials stay in ignored local storage.
