# Binding numerical context to existing M1 evidence

This continues the approved [numerical producer prerequisite for M2](M2_NUMERICAL_PRODUCER_PLAN.md).
`NumericalEvidenceBindingRepository.bind(record_id, parse_id, user)` links a
stored [context inspection](M1_NUMERICAL_CONTEXT_HISTORY.md) to exact evidence
from an explicitly selected, complete, sealed M1 parse. It reads existing data
and returns a typed binding. It creates no evidence, review, fact or publication.

## Exact source and word membership

The filing version, original blob/hash, SDK configuration, original page count
and page geometry must agree. A sparse page preparation cannot supply a complete
parse. Known partial-parse/backend-error diagnostics are rejected. The original
source, exact-word and table checks in the stored context must have passed.

Each selected whole native word must match exactly one eligible M1 text evidence
record by original page, complete original text, raw oriented rectangle and
canonical word envelope. Source-cell indices are not assumed to equal preparation
word indices. Existing evidence IDs and individual word boxes are retained;
words are never joined into a fabricated source span. OCR, missing support and
duplicate identical native support cannot silently pass.

For value, row label and period header, the preparation mapping must contain the
same complete native-word sequence. One retained artifact table must match all
three cells' grid dimensions, row/column/spans, header flags, text, raw cell box
and canonical box on the original page. Ambiguous or changed table membership
blocks binding. This does not settle issuer/period/currency/basis applicability.

The result retains role/ordinal, every word reference and its existing
`TextEvidence`, and the retained artifact table/cell IDs with exact word evidence
IDs. Artifact table/cell IDs identify the sealed parser sidecar. They are not
new persisted `CellEvidence` IDs. Preparation capture IDs never enter public
evidence-ID fields. Existing public source/evidence contracts are unchanged.

## Repository verification and history

The repository requires a current active administrator and uses one
repeatable-read transaction. It loads the immutable context record and a
`PARSED` job's actual artifact/configuration bytes, verifies their fingerprints,
source IDs and page counts, and physically verifies the original PDF. Every
linked evidence row, source page, original block, page geometry and evidence-box
set must match the projected sealed artifact. Caller-supplied evidence IDs or
approval snapshots are not accepted by this entry point.
The canonical artifact fingerprint must also equal the retained sidecar's
fingerprint. Rehashing differently encoded or duplicate-key JSON cannot make
the binding identify a different artifact from the one actually stored.

The parse ID is explicit. A later parse does not replace an earlier selection by
timestamp; bindings to both remain distinguishable. The context record's old
approval snapshots are retained. Binding does not establish that those approvals
remain applicable for a future acceptance operation, which must revalidate.

The `numerical-context-evidence-binding-1` identity binds the context IDs/hashes,
source, parse/artifact/processing hashes, linked words/grid and binding code
fingerprint. Bounds are 1,024 selected word references, 256 words per phrase and
4 MiB serialized output. Bounds fail without truncation. Fingerprints identify
the result; they are not signatures or actual review.

Every result remains `acceptance_eligible=false`, `review_required=true` and
`mandatory_m1_validation_complete=false`. The existing table/context gates stay
in place. This adds no dependency, migration, endpoint, frontend flow, required
environment variable or service. The preserved M1 database remains at 1–11;
independent M2/disposable installations use the unchanged loader through 13.

## Verification and real-data readiness

See the [measured binding report](../data/numerical-evidence-binding-validation-report.json)
for commands, exact fingerprints, test counts and disclosed repairs. Authored
fixtures declare native/processed data over blank PDFs to isolate engineering
contracts. They do not prove real transcription, financial accuracy or review.

```powershell
uv run --project backend --locked --no-sync --offline pytest backend/tests/test_numerical_evidence_binding.py
uv run --project backend --locked --no-sync --offline python scripts/check-migrations.py --test-file backend/tests/integration/test_numerical_binding_storage.py
```

The read-only real-data check verifies both existing numerical source-file
hashes and four retained real inspections. The preserved corpus has zero
matching complete parses for those documents. Trying to bind those inspections
to the unrelated existing three-page M1 parse returns `SOURCE_MISMATCH` in all
four cases. All 37 primary authority hashes remain unchanged. No real positive
binding, accepted numerical fact or research effectiveness is claimed.

Next produce and benchmark genuine complete parses of the original source
documents in the isolated producer environment, then exercise this binding on
their actual retained native evidence. Preserve source pages and original IDs;
do not invent a complete parse from sparse preparations. Complete the mandatory
versioned numerical validation, actual source-backed review, immutable acceptance
and atomic publication path before independent real M2 acceptance. Quotes remain
unavailable by the user's decision.
