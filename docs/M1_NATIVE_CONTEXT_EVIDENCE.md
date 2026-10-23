# Complete native source and scoped contextual M1 evidence

This implements the evidence-producer prerequisite approved on19October for M2.
On23October the user confirmed that M1 interfaces and existing data must stay
stable while the integration is completed. Work remains in the isolated M2
checkout and owned disposable databases. No primary corpus migration is implied.

## Source coverage and exact evidence

`parsing/native_source.py` decodes the intact original through the already pinned
Docling7.22.1 native parser. It loads one verified in-memory PDF snapshot, requests
pages lazily and releases native page data after each page. Layout, table
prediction, bitmap decoding and OCR are disabled for this stage. A bank retains
every original page, native word index/text, original bottom-left quadrilateral,
physical PDF geometry and a canonical receipt. The manifest is written only
after complete ordered coverage. The original PDF is never rewritten.

The bank has separate source/configuration/backend/package/code fingerprints.
Source limits remain64MiB/2,000pages; each page bank record is bounded at4MiB,
20,000words and the complete bank at1GiB. Replay checks source bytes, every
receipt, canonical JSON, native word order and actual original page geometry.

`parsing/native_context.py` combines that bank with one to32 explicitly selected
contextual captures from the existing pinned layout/table/OCR configuration.
These are separate stages with separate identities. Original native bottom-left
corners remain in the bank. The bridge checks the explicit height-minus-y
conversion against every original top-left corner in the actual contextual
capture, preserving both originals. Its initial calibration supports selected
unrotated pages with a full media/crop box at origin0. Other selected geometry
fails closed; it is not approximated.

The public evidence projection contains whole original words from those selected
context pages only. Its canonical boxes use M1's existing PDF-point coordinate
contract. The artifact retains all original page identities; it does not claim
layout, OCR, public evidence or table coverage on unselected pages. Selected
pages with missing original words or unresolved exact support cannot seal under
this strict initial profile. A complete native bank is not a complete layout/OCR
conversion and does not supersede the earlier full-converter benchmark.

Table previews retain their actual capture membership and opaque table IDs.
They remain previews, with zero public `CellEvidence` records. Existing numerical
binding checks still require exact word evidence and matching row/column/header
grid context; a larger combined SDK cell cannot stand in for an original word.

## Versioned persistence with existing interfaces

The new adapter identity is `regintel-native-context` version1.0.0. Its processing
configuration schema1.1.0 declares both stage configurations and the exact
selected page indices. It retains the existing artifact schema1.0.0 and existing
public text-evidence/API shapes. Existing parser, geometry, artifact-model and
legacy projection algorithms are unchanged.

Migration14 appends `parse_artifacts.format_version` with default1.0.0 and four
append-only tables: `native_parse_manifests`, `native_parse_source_pages`,
`native_parse_context_captures` and `native_parse_table_sources`. New sidecars
explicitly use format1.1.0. Existing sidecars continue through the original
validation branch. No old migration or sealed record is edited.

`NativeM1Producer.run` requires an explicitly submitted existing M1 job with the
new processing fingerprint and a current administrator. It checks prerequisites,
locks duplicate processing, re-verifies the stored original PDF, reloads actual
contextual captures and rebuilds the artifact before persistence. Parse tree,
complete native bank, selected capture/table membership, sidecar and `PARSED`
outcome commit atomically. Database gates reject incomplete or different
relational evidence. Failed processing creates no partial parse; terminal replay
does not create a new result. Existing `persist_parse` callers retain legacy
behavior through the extracted common persistence function.

M2's read-only binding repository recognizes the explicit new configuration and
checks the actual stored M1 evidence, blocks, page geometry and boxes. The
existing evidence repository reads those same IDs through its existing contract.
This does not create numerical candidates, override mandatory context checks,
approve definitions/identities, accept observations or publish a corpus.

The producer is an internal programmatic path. The legacy Celery worker and
upload UI do not automatically select this native/context profile. Runtime
selection, mandatory numerical validation/review and acceptance/publication
remain necessary before these inputs can be consumed as accepted M2 facts.

## Capture command and measured verification

Inside the approved pinned Linux parser image, with the checkout/originals
mounted read-only and a fresh ignored output directory mounted writable:

```text
python scripts/capture-native-source.py --source /workspace/.cache/analysis-source-review/premier-energies-prospectus-20240830.pdf --source-sha256 aeac8f5598627bf5704d0ae714c4ec536570f320cbb552f682a29ed3d3fc14ca --output-dir /output/premier
```

Use the existing non-root/read-only/network-none container policy. This CLI has
no database, credential or provider path and needs no model download. Its exit0
means a complete native source bank, never financial acceptance. Raw banks,
captures and originals stay ignored. The separately measured report records
actual runtimes, resource limits, hashes, test outcomes and real-source binding
coverage. Authored blank-PDF fixtures test integrity and failure handling; they
are not parser accuracy, financial review or research gold.
