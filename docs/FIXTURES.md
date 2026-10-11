# M0.6 — Synthetic fixture scope and verification

Completed2026-10-06 (Asia/Calcutta), after M0.5 local/full/live acceptance. This phase
authors synthetic source recipes, reproducible PDF generation, contract/adversarial
cases and integrity helpers. It does not implement Docling/OCR, source acceptance,
amendment resolution, publication or provider calls. No real-filing gold data or
effectiveness result is produced.

## Implemented source family

Clearly invented Helio, Prism and Cobalt fixture companies use fixed UUIDv4-shaped
IDs and synthetic labels on every page. Three sources are generated: a four-page
base, one-page explicit corrigendum and one-page later conflicting disclosure.
Recipes/expected cases stay in source; PDFs and manifests stay under ignored
artifacts/fixtures. Base pages cover a
contextual financial table, exact text/qualifiers/negation/injection, separate
cross-page support, negative media/crop offsets, rotations0/90/180/270 and a real
image-only page with authored transcription. Parent links and five amendment
effect labels are explicit fixture expectations, not published decisions. The
supersession identifies an exact base-page lending quote and explicitly retains
the separate scanned statement. The later source asserts conflicting ownership
without an invented parent or blanket replacement. Raw PDF media/crop boxes and
authored highlight boxes are distinct; highlights are not measured parser output.

Runtime-model contract §8 requires18 adversarial categories. Include a positive
supported directed relation, incomplete ownership context, wrong column/year/unit,
invented IDs/modified quote/direction, co-occurrence/undisclosed supplier,
uncertainty/negation, unknown period, missing value, injection, unsupported JSON/
paraphrase, OCR ambiguity, conflict and mocked timeout/refusal. Keep structural
contract validity separate from the future evidence/context/runtime expectation.
Well-formed unsupported IDs/claims intentionally pass shape validation. The31
cases contain29 wire-shape payloads (28valid, one invalid JSON numeric financial
value) and two mocked timeout/refusal events with no provider output. Exact effect
evidence IDs and observation source anchors are checked as fixture integrity.

## Dependencies selected before implementation

Development-only exact pins verified against official Python3.12 metadata/licenses:
ReportLab5.0.1 (BSD), pypdf6.19.0 (BSD-3-Clause, typed), Pillow12.3.0 (MIT-CMU) and
types-reportlab5.0.0.20260911 (Apache-2.0). ReportLab also resolves charset-normalizer
(MIT), frozen by uv.lock. Stubs are required for strict mypy; verify their5.0.0
target against the5.0.1 APIs actually used. No production parsing/model dependency,
new migration, environment variable or infrastructure is required.

Use invariant PDF generation and fixed metadata. Compare independent generations
on the tested runtime; do not claim universal cross-platform byte parity. Inspect
page counts, extracted native text, raw boxes/rotations, raster-only content,
source references/spans/cells and sidecar hashes. Reject unexpected references or
tampering in integrity helpers. Render all final pages using bundled Poppler and
inspect the PNGs before closure. Generated PDFs remain excluded from Git.

## Acceptance

1. Required source/context/geometry/amendment/adversarial coverage is explicit.
2. Two fresh generations are byte-identical locally; hashes/sidecars agree.
3. Current Pydantic/TypeScript fixtures agree on structural validity; future gate
   outcomes remain authored expectations rather than fake passing gate tests.
4. Meaningful fixture integrity/failure tests, lint, strict typing, build and the
   expanded check runner pass. Review source/runtime boundaries and update durable
   phase/current/continuation/dependency records before stopping at the M1 deck gate.

Primary references: [ReportLab5.0.1](https://pypi.org/project/reportlab/5.0.1/),
[pypdf6.19.0](https://pypi.org/project/pypdf/6.19.0/),
[Pillow12.3.0](https://pypi.org/project/pillow/12.3.0/),
[ReportLab stubs](https://pypi.org/project/types-reportlab/5.0.0.20260911/).

## Generation and implemented checks

Source recipes/evidence live in backend/src/regintel/fixtures/sources.py;
pdf.py owns generation and adversarial.py owns the case suite/integrity helper.
scripts/generate-fixtures.py creates three PDFs and manifest.json;
scripts/export-fixture-cases.py exports ignored frontend case data. Both --check
modes detect drift without writing. Bootstrap and CI generate the prerequisites;
the check runner verifies them before lint/type/tests.

The PDF generator allows only this workspace's artifacts/fixtures output, rejects
symlink/junction/non-directory ancestors and unexpected entries, refuses changed
existing artifacts and exclusively creates missing files. Identical outputs are
preserved. Source recipe changes require reviewing/preserving the earlier outputs
before regeneration; no broad delete is part of the workflow.

Seven PDF tests and nine adversarial tests verify two independent byte-identical
local generations, hashes, fixed IDs, six pages/rotations/negative box origins,
image-only content with no extracted text, no PDF active actions, merged headers,
cross-page supports, exact source-scoped effects, output confinement and tampering.
Forty frontend tests verify current wire-shape decisions without mutating raw
strings. They do not execute the authored future_expectation as acceptance logic.

Final scripts/run-checks.ps1 exited0:319 backend tests (58 integration deselected),
212 frontend tests, three Chromium checks (9.1s), Ruff47 files/strict mypy33 sources,
47-package offline lock and schema/PDF/case drift checks. The58 live database/auth
cases passed at M0.5 closure; fixture-only changes did not alter those behaviors.
Actionlint and PowerShell/Bash syntax passed; hosted CI remains unrun.

Bundled Poppler rendered all six pages; each was visually inspected. The corrected
corrigendum was rendered/inspected again after the source-scope review fix. Native
text, intentional rotations, raster source and table labels are readable without
clipping. Missing display-font substitution warnings were non-blocking for these
ASCII fixtures. Earlier known generated files were preserved under ignored
.cache/m06-first-generation before final regeneration; unrelated files were not
removed. Independent source/integrity review found no remaining M0.6 blocker.

M0 is complete. Actual deck verification gates M1; parser/OCR/provider/evidence
acceptance, real source ingestion and research effectiveness remain future work.
