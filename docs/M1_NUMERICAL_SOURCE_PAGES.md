# Original-page preparation for the numerical producer

The user approved the bounded [M1 prerequisite extension](M2_NUMERICAL_PRODUCER_PLAN.md)
on 19 October 2026. This first checkpoint adds a separate preparation artifact
and an offline probe. It does not upload or publish a filing, create accepted
cell evidence, interpret financial context, or supply a numerical M2 input.

The later [joint-context inspector](M1_NUMERICAL_CONTEXT.md) consumes stored
preparations through a separate internal schema. It can propose explicit
annual/context interpretations, but remains permanently ineligible for
acceptance. The original preparation contract and parser are unchanged.

## What is retained

`regintel.numerical.source_pages` checks one successful SDK page capture against
the immutable original PDF hash, actual page count/geometry, requested original
page number and the selected pinned SDK configuration. It retains individual
native word originals and their reported quadrilaterals, transformed into the
existing unrotated PDF-point frame without clipping or fitting. Raw capture and
preparation code hashes make replay inputs/configuration explicit.

The old parser artifact remains unchanged. This artifact has its own
`numerical-source-page-1` schema and `SINGLE_ORIGINAL_PAGE_PREPARATION` scope;
its `acceptance_eligible` field is permanently false. A selected-page capture
cannot be mistaken for a successful full-filing parse.

Processed table grids remain previews. Word-center membership and exact native
word-sequence/whitespace agreement propose a mapping only. Every mapping requires
review; no combined source span, exact cell rectangle or row/column semantics
is fabricated. OCR/unknown transcription, missing geometry/text, wrong text or
ambiguous reuse of a word leave mappings unavailable. Non-native words inside
a preview region cannot be silently dropped to create a match.

Bounds: original PDF and raw capture each at most64 MiB; source at most2,000
pages; one requested page; at most20,000 words, eight table previews and2,000
total preview cells; at most4,000,000 word/cell comparisons. Bounds fail explicitly.
These are preparation limits, not new application upload/worker defaults.

## Run and replay

The script has no database, API, publication, model-provider or quote-feed path.
Use `--models` only inside the existing pinned Linux parser image, with the
repository's current script/source extension and original PDF/model/configuration
mounted read-only. Keep the existing non-root UID10001, read-only root filesystem,
network disabled, dropped capabilities and a writable temporary directory. The
verified probes used two CPUs,3 GiB memory and a768 MiB temporary filesystem.
Do not install Docling on the native Windows API environment.

Inside that controlled environment, with explicit mounted paths:

```bash
python /tools/probe-numerical-page.py \
  --models /models \
  --source /sources/original.pdf \
  --source-sha256 VERIFIED_ORIGINAL_SHA256 \
  --pdf-page 30 \
  --parser-config /configuration/parser-runtime-config.json \
  --output-dir /outputs/fresh-page-capture
```

The original file is passed intact to the SDK with a one-based page range.
No subset/reconstructed PDF is substituted. The script disables socket connects
and requires the installed SDK settings to match the selected configuration.

Replay an existing `raw.json` with the normal locked native environment; no
Docling/model installation or database is needed:

```powershell
uv run --project backend --locked --no-sync --offline python scripts/probe-numerical-page.py --source D:\sources\original.pdf --source-sha256 VERIFIED_ORIGINAL_SHA256 --pdf-page 30 --parser-config data/parser-runtime-config.json --replay D:\captures\raw.json --output-dir D:\captures\fresh-replay
```

Use the source packet's actual filename/hash/page and a fresh absolute output
directory. The command writes `raw.json`, `prepared.json` and `report.json` only
after successful validation. An existing output directory is refused without
overwriting it. Exit0 means `PREPARATION_ONLY`; exit1 means failure, with raw
diagnostics omitted. Neither exit code is a fact-acceptance result.

Original PDFs, raw/prepared captures and QA PNGs remain ignored local cache.
Another clone must acquire/hash its own approved originals and create its own
captures. Committed measured metadata does not recreate parser output or data.

## Measured scope and next implementation

Four original table/context pages from the existing seed-company pair were
sampled successfully offline. The reusable CLI was then exercised in separate
Linux processes for both table pages, with native replay producing identical
prepared bytes. Whole-page QA verified the four selected original-word boxes.
See `data/numerical-source-pages-validation-report.json` for exact versions,
hashes, counts, timings, tests, preservation checks and limitations.

These samples do not measure whole-filing conversion time or table/relation
accuracy. Unmatched previews remain in the artifact; no coverage is truncated
or converted into accepted facts. The manual-testing corpus remains unchanged.

Versioned page/word preparation persistence is described below. Next implement
exact joint cell/context support and a bounded supported link for issuer,
metric, period, unit, currency and basis.
Retain the existing mandatory abstention until those links pass M1 gates and
actual review. Full duration interpretation, audited numerical acceptance,
publication and all six real M2 acceptance categories remain unfinished.

## Append-only page and word storage

The 20 October extension adds `regintel.numerical.models` and
`regintel.numerical.repository`. This is a producer library; no new API endpoint
or browser flow is exposed. An existing uploaded filing version and its immutable
source blob must already exist. `NumericalRepository.save` takes that version ID,
the retained raw SDK bytes, the one-based original PDF page and a current user.
It verifies the content-addressed source and rebuilds the preparation against the
selected SDK configuration before storing anything. It does not dispatch a job or
mark a full parse complete.

New migration `0012_numerical_preparation.sql` creates only
`numerical_page_captures` and `numerical_source_words`. The capture retains raw
and canonical prepared bytes, hashes, page identity, configuration/code identity,
submitted administrator and authentication version. Every original word is also
stored separately with its own hash. A composite foreign key binds the uploaded
source version; a deferred database check seals the complete matching word set
in the same transaction. Updates, deletes and truncation are rejected. Changed
captures obtain distinct content-derived IDs while old records remain readable.
Repeated and concurrent saves of identical input return the original record.

Both reads and writes check the current database role, active status and
authentication version. A supplied `admin` role alone cannot grant access.
Database insert triggers also check the administrator, source membership,
fingerprints, metadata and permanently false acceptance eligibility. These checks
protect preparation consistency; they do not independently prove the parser's
text or financial interpretation.

`NumericalWordRef` identifies one capture, original word index, half-open Unicode
code-point offsets and exact quoted text. Resolution requires native transcription
(`from_ocr=false`), the exact original substring and retained raw/canonical
geometry. Its `ORIGINAL_WORD_ENVELOPE` is the whole original word rectangle even
for a substring; no glyph rectangle or combined multi-word span is invented.
The result remains `acceptance_eligible=false` and `review_required=true`.
Historical reads check sealed database bytes; they do not reverify the current
physical PDF. Future acceptance/source-viewer paths must verify that source again.

Migration 12 has been exercised only in owned disposable databases on this host.
The original M1 checkout and manual-testing database remain on migrations 1–11;
do not apply 12 there during parallel M1 testing. A fresh M2 clone's normal
migration command discovers 12. No old migration is edited. No new dependency,
required environment variable, service, quote source or paid provider is added.

This storage still does not create public `CellEvidence`, accepted observations,
review decisions, corpus versions or M2 financial inputs. Joint row/header/issuer/
metric/period/unit/currency/basis evidence, mandatory numerical gates, actual
review and publication remain the next producer work.

## Additional source-context intake

After storage verification, four more original pages from the same existing
document pair were captured offline: each issuer cover and each currency/unit
definition page. All four native replays reproduce their prepared bytes exactly.
Complete original pages and six groups of separate original-word rectangles were
visually inspected. `data/numerical-context-intake-report.json` records source,
configuration, code, raw/prepared hashes and unaccepted word-index locators only.
No raw capture, source PDF or QA image is committed.

These ranges locate separate native words. They are not combined exact spans,
accepted source evidence or approved semantic links. The full unit-convention
paragraphs retain their whole-number, otherwise and third-party exceptions.
The currency page's exchange-rate table is outside the proposed support; no FX
conversion is implemented. Issuer/CIN words still need an explicit link to the
approved canonical entity and the filing's financial statements.

The Waaree cover's SDK warns that two PDF cells were dropped from a processed
table grid; four of 15 preview mappings remain unavailable. The original native
issuer/CIN words have their own retained geometry and do not depend on those
grid cells. The intake does not claim complete table/transcription coverage.
The four additional captures remain files only: they were not inserted into the
primary or disposable database. The prior four-page storage proof is a separate
measured result. Joint context contracts, mandatory gates and actual review
remain required before either set can support a numerical observation.
