# Refresh numerical source and approval checks

Updated 20 November 2026. This workflow refreshes machine checks for an existing
numerical source selection after its prerequisites or checking configuration
change. It does not approve a metric, issuer, policy, context or financial fact.
The real-source prerequisite decisions remain pending until a designated
reviewer supplies them. This guide does not assert that the updated UI is
currently served by a running installation.

## Administrator workflow

1. Sign in to **Administrator workspace** and select **Numerical filings**.
2. Open the stored gate from the queue, or enter its **Saved numerical gate ID**
   and select **Load numerical review**. Inspect the retained source selection.
3. After the required registrations have genuinely been reviewed and recorded,
   select **Refresh source and approval checks**.
4. Inspect the returned checks. If the inputs and configuration are unchanged,
   the same gate is returned. Otherwise the UI opens the refreshed gate and
   displays the previous gate ID; the previous records remain in history.

The pending prerequisite proposals and their exact source anchors are in
[the M1 review packet](M1_NUMERICAL_PREREQUISITE_REVIEW_PACKET.md). Repeated
refreshes cannot replace those decisions. A refresh may still return unresolved
or quarantined checks.

If the response is lost or cannot be verified, the UI retains the exact request
and offers **Retry the same source refresh**. Gate selection and conflicting
review, candidate and acceptance actions remain locked until a verified response
arrives. Retention is for the current mounted workspace; save the displayed
gate ID before leaving or signing out. A later retry checks current approvals
again, so approvals recorded between attempts can produce a new gate.

## What is preserved and what is refreshed

The backend verifies the selected historical gate ID and both its input and
result hashes. It creates or reuses the current context snapshot and its base
gate in one database transaction. The draft, captured pages, parse version,
filing/blob identity, source hash, exact phrases, table cells and evidence IDs
must match the historical selection. A failed refresh commits neither half of
the context/gate operation. Existing records are not overwritten.

The new snapshot uses current approved registry, metric and numerical-policy
state and the current checking configuration. Refresh produces base machine
checks: it does not copy an applicability attestation from a resolved gate to
the refreshed gate. An unchanged or previously existing gate can display a
genuine context review already recorded for that exact gate. The refresh itself
creates no applicability or context decision, candidate acceptance or
publication.

After the prerequisites pass, the normal actions remain separate: inspect and
record any required applicability review, rerun with that recorded review,
confirm context, prepare and save the candidate, record its acceptance, then
build and publish the corpus through M1. Each step retains its own evidence,
authorization and current-prerequisite checks. M2 consumes the resulting
published corpus; a refreshed inspection alone supplies no accepted numerical
facts.

## API contract

The administrator-only route is:

```text
POST /v1/admin/numerical/gates/{gate_id}/refresh
```

The request has schema version `numerical-refresh-request-1` and these fields:

| Field | Required selection |
|---|---|
| `schema_version` | `numerical-refresh-request-1` |
| `gate_run_id` | The exact selected historical gate ID, matching the URL. |
| `gate_input_sha256` | The stored gate input hash. |
| `gate_result_sha256` | SHA-256 of the canonical stored gate result bytes. |

The request contains no new source selection or approval fields. The server
rejects a path/body mismatch or a hash mismatch. The result uses
`numerical-refresh-result-1`, echoes the request, records the previous context
ID, reports whether the context and gate changed, and includes the verified
gate/binding/review packet. Its `acceptance_eligible`,
`mandatory_m1_validation_complete` and `publishes_fact` fields remain false.
Private response metadata cannot imply a published corpus version.

The frontend verifies the echoed selection, transition flags and exact source
membership before opening the returned packet. An unverifiable response leaves
the original request pending. Identical refreshes against unchanged current
inputs reuse the retained result; the request is not an approval or a promise
that future approval state cannot change.

This change adds no dependency, database migration or environment variable.
Verification results are recorded separately in the project checkpoint records.
