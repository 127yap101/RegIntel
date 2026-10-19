# Original-page preparation for the numerical producer

The user approved the bounded [M1 prerequisite extension](M2_NUMERICAL_PRODUCER_PLAN.md)
on 19 October 2026. This first checkpoint adds a separate preparation artifact
and an offline probe. It does not upload or publish a filing, create accepted
cell evidence, interpret financial context, or supply a numerical M2 input.

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

Next implement versioned persistence of exact word/cell/context support and a
bounded supported link for issuer, metric, period, unit, currency and basis.
Retain the existing mandatory abstention until those links pass M1 gates and
actual review. Full duration interpretation, audited numerical acceptance,
publication and all six real M2 acceptance categories remain unfinished.
