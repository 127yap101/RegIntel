# Bound numerical gate and immutable history

25 October 2026. This is an internal step in the approved M1→M2 prerequisite,
on `codex/m2-comparison`. M1's public contracts and original corpus remain stable.
The separate `bound-numerical-gate-1` result is not a legacy `ValidationRun` and
cannot be passed to its acceptance or publication path.

## Inputs and checks

`BoundNumericalGateRepository` takes a retained numerical context record and a
complete sealed M1 parse. It rechecks the original physical source and loads the
current issuer registry, metric and numerical-policy snapshots in one consistent
administrator transaction. The existing binding implementation verifies exact
stored M1 words, boxes, source pages and preview membership. No page-level citation
or synthetic combined quote replaces the original evidence.

The deterministic gate records these ordered checks:

| Check | Required support |
|---|---|
| SOURCE | Original source/version and capture/configuration membership |
| EXACT_WORDS | Original word text, coordinates and exact references |
| TABLE | Selected value, row and column/header membership |
| ISSUER | Source issuer/CIN and current approved entity context |
| METRIC | Current approved metric and numerical policy |
| VALUE | Exact raw value and deterministic decimal normalization |
| UNIT | Explicit supported source unit |
| CURRENCY | Explicit supported currency context |
| PERIOD | Supported dates and instant/duration context |
| BASIS | Supported standalone/consolidated reporting basis |
| CONTEXT_SCOPE | Applicable local or explicitly supported cross-page context |
| FRESH_CONTEXT | Current snapshots compared with the immutable retained input |
| BOUND_EVIDENCE | Exact retained context linked to actual sealed M1 word evidence |
| SOURCE_LANGUAGE | Recognized instructions fail; examples/qualifications require review |

The first eleven checks reuse the existing numerical inspector. Recognized
instruction/qualification patterns are a bounded engineering control, not proof
of detecting every adversarial or ambiguous sentence. Application gates remain
mandatory even for administrator-supplied data.

Any failed check produces `QUARANTINED` without a quantity proposal. Unresolved
checks produce `REVIEW_REQUIRED`. All checks passing produces `READY_FOR_REVIEW`.
Every state retains `review_required=true`, `acceptance_eligible=false` and
`mandatory_m1_validation_complete=false`. This step never claims a human review
or completion of the legacy M1 acceptance contract.

A changed approval snapshot requires a new inspection/binding before its proposal
can advance; it is not grafted onto old history. Changed source/draft/configuration
inputs fail freshness. Historical reads preserve their stored inputs. Known-current
configurations replay deterministically; older configurations remain explicitly
identified by their recorded hash rather than being relabelled as current results.

## Persistence and use

Migration `0017_bound_numerical_gates.sql` adds one append-only audit table,
`bound_numerical_gate_runs`. Migrations 1–16 are frozen. The new table checks
current administrator identity, complete parse membership, exact retained context,
input/result fingerprints, ordered outcomes and existing word IDs/spans. It cannot
write facts, acceptance reviews or corpus publication. Identical concurrent requests
retain one exact result and the original submitting administrator snapshot.

The interface is programmatic, for an already configured `NumericalRepository`
and authenticated current administrator `User`:

```python
from regintel.numerical.gate_repository import BoundNumericalGateRepository

gates = BoundNumericalGateRepository(source)
stored = gates.run(context_record_id, sealed_parse_id, user)
assert gates.get(stored.result.id, user) == stored
```

There is no new public API, runtime worker selection or acceptance command. A
teammate can run the dedicated disposable-database test in the module run guide;
its authored PDFs are engineering controls, not gold financial annotations.
The measured real-filing proof and exact source hashes are recorded separately in
[the continuation report](../data/module-continuation-validation-report.json).

## Remaining producer work

The real proof reuses the two intact Premier/Waaree originals and retained pinned
captures in an owned disposable corpus. It seals 1,184 native pages and 5,699 exact
M1 word records across eight selected context pages. All four recorded gates
replay identically and remain `REVIEW_REQUIRED`. The unresolved checks concern
issuer/metric approval, conditional unit/context applicability and source
qualifiers; Waaree also retains basis review. There are no registry/metric/policy
approvals, acceptance audits, fact observations or corpus versions. The owned
database is removed and all 37 primary authority fingerprints remain unchanged.
These are actual gate outcomes, not independently annotated financial accuracy.

Complete the versioned mandatory acceptance/review adapter, preserving the existing
M1 evidence, permission and financial-context gates. Real issuer/metric/policy
approval and supported cross-page applicability need actual evidence-backed
decisions. Then test immutable acceptance/publication and independently reviewed
real M2 expected calculations. Quotes remain unavailable by the user's decision.
The original M1 database must not be migrated or reset for these checks.
