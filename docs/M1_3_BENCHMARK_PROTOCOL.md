# M1.3 engineering parsing benchmark protocol

The benchmark measures transcription against the existing authored fixture recipes.
It does not run Docling, create evidence, accept facts or establish research
effectiveness. The first actual three-fixture conversion record is retained below;
real-filing reference checks and geometry/context calibration remain separate. The 23
unit cases verify metric arithmetic, strict input handling and source binding;
their controlled transcriptions are not OCR results.

## Inputs and reference boundary

Use the exact source PDF from `artifacts/fixtures/manifest.json`, the complete raw
probe capture, and the JSON summary printed by that same probe invocation. The
helper checks the capture's source SHA256 against the selected fixture manifest,
checks manifest text against the frozen code recipe, and retains the manifest and
capture file hashes in its result. When runtime measurements are supplied to the
CLI, their output byte count must equal the actual capture file size. Preserve the
original capture and its summary together; byte-count matching alone does not
prove that an independently supplied summary came from the same invocation.

The probe has inspected `page_no`, `cells`, `orig`, `text` and `from_ocr` fields.
The benchmark projects those fields into strict DTOs and requires original text.
It does not substitute processed text, Markdown, document export text, model
confidence or a best-performing alternative for missing `orig`. Unused upstream
fields remain in the original capture. This projection is deliberately narrower
than the artifact adapter.

Field source: [pinned Docling core TextCell definition](https://raw.githubusercontent.com/docling-project/docling-core/v2.99.0/docling_core/types/doc/page.py).

The frozen base fixture has four source pages:

| Viewer page | PDF rotation | Authored category |
|---|---:|---|
| 1 | 0 | Native relationship/context/injection text |
| 2 | 90 | Native table with merged unit header, duplicate numeric values, dash and blank |
| 3 | 180 | Entirely raster page, including header/footer; two scanned disclosure lines |
| 4 | 270 | Native geometry-marker text |

The raster page is **page 3**, not page 4. Its authored disclosure is:

```text
SCANNED SOURCE: Cobalt Fixture Ltd lends INR 10 crore
to Prism Fixture Pvt Ltd.
```

Full-page references include all drawn header/title/footer strings and nonempty
block lines from the inspected native and raster rendering recipes. The raster
footer literally says that no OCR has been run because it was authored before
runtime conversion; retain this source text unchanged during comparison.
Table blank cells draw no text and are explicitly excluded from transcription
success claims. Dash remains the literal `-`; no number is inferred from either.

The reference is authored source text, rather than a manually transcribed rendered
image. Crop clipping, actual rendering and any text outside the visible region
must be inspected and reported separately. Do not silently modify the reference
to improve a score. The existing authored evidence rectangles are not measured
parser geometry and must not be used as proof of frame calibration.

## Metric definitions

Preserve `reference_raw` and `observed_raw` exactly. The observed page string joins
all captured cell `orig` strings with a newline in their captured order. Raw exact
match therefore tests that declared representation, and can differ when a parser
uses different cell segmentation even if the visible text is unchanged.

For CER/WER only, apply Unicode NFC and collapse every Unicode whitespace run to
one ASCII space, trimming outer whitespace. Preserve case, punctuation, digits,
decimal points and symbols. This explicit comparison normalization never changes
stored source text or authoritative values.

- Character edits are unit-cost Levenshtein insertions/deletions/substitutions over
  normalized Unicode code points. CER is edits / reference code points.
- Word edits use the same distance over normalized whitespace-delimited tokens.
  WER is edits / reference tokens. No language-specific tokenizer is implied.
- Zero-length reference denominators produce `null`, with observed text and edit
  counts still reported. Error rates can exceed 1; never cap them.
- Raw and normalized exact-line counts use multiset intersection, so one observed
  line cannot satisfy duplicate reference lines. Report unmatched reference and
  observed lines, plus ordered line edit distance. Line metrics depend on cell
  segmentation and are diagnostic, not an independent OCR accuracy estimate.
- Per-block raw/normalized substring presence is a bounded engineering aid. It
  proves neither table row/header context nor exact geometry, OCR truth or accepted
  financial meaning. Empty authored blocks have `null` presence outcomes.

Retain actual page coverage and native/OCR cell counts, and count cells whose
processed `text` differs from `orig`. Missing capture pages are explicit and their
reference text scores as deletions; extra or duplicate pages are refused. Missing
original text is refused rather than repaired. Computation has explicit text and
edit-work bounds; exceeding them is an unavailable benchmark, not silent
truncation or a fabricated score.

## Actual conversion, timing and memory record

For the first actual run record the configured one-engine RapidOCR ONNX English
tiny model, CPU/thread/provider settings, package/image/configuration/model hashes,
all fixture page counts and the raw transcription errors. Record any rejected or
missing original text, incorrect table structure, unavailable cell boxes, crop
and rotation failures. Keep the original output; bounded same-engine tuning needs
a separate capture/configuration hash and comparison record.

The controlled probe's `initialization_seconds` measures converter construction
and imports. Models are lazily initialized during conversion, so this is **not**
separately measured model-loading time. `conversion_seconds` is cold conversion
including that lazy initialization. `max_rss_kib` is the Linux process lifetime
peak resident set, including imports/models/conversion; it is not an incremental
conversion-only allocation. The benchmark copies supplied runtime fields without
inventing them. Without a summary, runtime measurements remain `null`.

Example native invocation, after actual capture generation:

```powershell
& backend/.venv/Scripts/python.exe -m regintel.parsing.benchmark `
  --capture D:\RegIntel\.cache\m1-3-probes\base.json `
  --reference-manifest D:\RegIntel\artifacts\fixtures\manifest.json `
  --fixture-key base `
  --measurements D:\RegIntel\.cache\m1-3-probes\base-runtime.json
```

The paths above illustrate expected inputs and do not imply those probe files
exist. The helper prints a JSON report and does not overwrite any source/capture,
download models, write database records or run a second OCR engine.
CLI JSON uses ASCII Unicode escapes so that Windows legacy console encodings
cannot corrupt or reject an actual OCR transcription. Decoding that JSON restores
the exact original strings; the UTF-8 raw capture and its file hash remain unchanged.

For the real three-page Premier Energies source, use manually selected and
transcribed exact snippets from the original PDF, record page/snippet IDs and
the reference transcription method, then apply `score_transcription` to the
bounded paired original strings. Report actual sample counts and limitations.
Do not reuse synthetic full-page references, call parser output the real-source
gold, or claim that this real source supplies raster pages when it does not.

## Verification completed for the helper

Configured Ruff and strict mypy passed. A first pytest invocation passed 22 cases
but its default Windows temporary-directory setup failed for the CLI case. A
repeat using fresh project-local `--basetemp` and `-p no:cacheprovider` passed all
23 cases in 0.62 seconds. The final repeat after adding runtime byte-count binding
passed the same 23 cases in 0.91 seconds, with Ruff/format/mypy also passing.
These are helper verification results only. A subsequent actual OCR capture exposed
a Windows cp1252 stdout failure on a Greek epsilon. CLI JSON now uses ASCII escapes
without changing decoded originals; the Unicode/emoji regression and all 23 cases
passed in 0.54 seconds, with configured Ruff/format/mypy passing.

## First actual fixture record — 7 October 2026

The root agent supplied real pinned-worker captures; this helper measured them
without running another conversion. Complete raw captures, matching probe summaries
and generated benchmark reports are retained under the ignored directory
`D:\RegIntel\.cache\parser-probes\20261007-v1`. The manifest source hashes matched
all three PDFs, and each supplied summary's output byte count matched its capture.
The fixture set is six pages: five native pages and one raster page.

| Source | Construction/imports seconds | Cold conversion seconds | Linux peak RSS KiB | Native/OCR cells |
|---|---:|---:|---:|---:|
| synthetic-base.pdf, four pages | 21.541212578 | 25.667942524 | 1,915,820 | 41 / 4 |
| synthetic-corrigendum.pdf, one page | 16.168683938 | 12.032678112 | 1,274,908 | 13 / 0 |
| synthetic-later-conflict.pdf, one page | 14.369924386 | 13.902786990 | 1,214,776 | 4 / 0 |

All summaries reported `success`, `network_disabled=true`, and zero network
attempts. These are cold local engineering timings and process lifetime memory
measurements, rather than comparative research performance or production sizing.
The attempts counter observes patched Python socket.connect/create_connection;
it is not a native-library or DNS attempt audit. Docker networknone isolates the
whole process. Preserve that scope when reporting the actual zero counter.

| Source/page | Reference characters / edits | Sequential CER | Reference words / edits | Sequential WER | Exact normalized lines / reference |
|---|---:|---:|---:|---:|---:|
| Base 1, native | 965 / 142 | 0.147150259 | 156 / 22 | 0.141025641 | 16 / 16 |
| Base 2, native table | 405 / 142 | 0.350617284 | 68 / 22 | 0.323529412 | 21 / 21 |
| Base 3, raster | 224 / 153 | 0.683035714 | 37 / 28 | 0.756756757 | 3 / 5 |
| Base 4, native | 217 / 109 | 0.502304147 | 31 / 14 | 0.451612903 | 4 / 4 |
| Corrigendum 1, native | 809 / 142 | 0.175525340 | 121 / 22 | 0.181818182 | 13 / 13 |
| Later conflict 1, native | 234 / 119 | 0.508547009 | 39 / 22 | 0.564102564 | 4 / 4 |

All 58 native reference lines matched exact original cell strings one-to-one.
Their sequential CER/WER is nonzero because the captured low-level cells put the
footer before body text, whereas the declared authored reference puts it last.
Those reading-order edits must not be described as character recognition mistakes.
The raw captures and sequential metrics have been preserved without reordering.

On raster page 3, the two scanned disclosure lines and fixture header matched
exactly as individual lines. The two disclosure lines arrived in reverse order;
the title line was gibberish, and the authored raster footer was missing. The
full-page result is therefore three exact reference lines out of five, with four
observed OCR lines. Neither the two successful lines nor the full-page score proves
general OCR accuracy. The full two-line block substring test fails because of its
reversed order, even though both separate line strings match.

The root adapter review also records a table structure failure: the SDK produced
four rows by five columns and 14 cells with zero header flags, against the authored
six rows by four columns and merged unit header. The native text includes both
`100.00` strings and a literal dash, but that does not validate row/column/basis
context. All 14 SDK table cells lacked original text and remain unavailable for
independent exact cell support. Geometry was still an uncalibrated candidate frame
at this checkpoint; authored boxes are not proof of parser highlights.

Configuration freeze was also unresolved at this checkpoint. The three capture
configuration hashes differed solely because disabled
`chart_extraction_options.model_spec.supported_engines` is a set serialized in
different process orders. The root agent was informed to canonicalize this known
unordered field before freezing configuration. Original capture hashes and their
original configuration identities remain retained, and these reports do not claim
a single already frozen cross-process configuration.

The real Premier Energies source remains outside this fixture comparison. A
manually checked real-source snippet set, original-render geometry calibration,
table context recovery/review and later persisted evidence are separate gates.

## 9 October review checkpoint

All four fixture and three original Premier annotated copies were rendered and
visually inspected. The selected crop/rotated/top-left frame aligns this pinned
backend's native/OCR raw quads with original PDF coordinates, including negative
origins and rotations0/90/180/270. This bounded calibration does not establish
universal geometry accuracy. Assembled SDK boxes now have explicit unavailable
raw geometry and remain preview data; table provenance is retained even when
mapping is incomplete. Old capture/candidate identities are preserved.

data/parser-validation-report.json records four small real metadata/heading
snippets that match exactly and a separately disclosed currency-glyph challenge.
The visual price-band line includes three rupee glyphs absent from native orig:
67reference characters/3edits;14reference words/3edits. Selection is manual and
small, with an explicitly bounded prefix comparison for the addendum heading.
Do not report this as filing-wide accuracy, a gold set or financial validation.

Canonicalizing only known set-valued supported_engines lists gives one semantic
SDK identity across all four historical configurations; optional null metadata
is preserved. Original captures remain untouched. The final Linux cross-process
execution/configuration check is pending, so the status in the validation report
remains incomplete. No persisted evidence, accepted fact or corpus publication.
