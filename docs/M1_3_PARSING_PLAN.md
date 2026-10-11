# M1.3 — Versioned Docling parsing and one CPU OCR engine

Prepared 2026-10-06 from read-only repository inspection and official publisher
documentation/source. This plan follows the approved M1A plan and fixed stack.
It records ordinary phase choices; it does not advance M1.2, authorize acceptance
or publication, or establish tested parsing capability.

## Status and evidence boundary

Current implementation checkpoint2026-10-07: M1.2 is complete. The proposed
Core2.98.0 pin below was incompatible with parser7.22.1's explicit >=2.99.0
requirement; the exact locked choice is now Core2.99.0. The121-package lock/native
60-package default boundary passes; actual worker build awaits the existing
Docker engine.15 model/config/card/license files were acquired anonymously and
weight hashes matched publisher expectations. DTO/geometry125 unit tests pass;
actual Docling conversion/OCR/frame calibration remains unverified. Historical
research statements below describe preparation, not completed runtime acceptance.

At preparation, M1.2 runtime acceptance is still active. M1.1 immutable storage
and shared evidence shapes exist. The acquired real Premier Energies SEBI
addendum/corrigendum has three pages and a source/hash manifest; preliminary
native extraction and visual inspection are recorded in CURRENT_STATE.md.
Neither that inspection nor the synthetic fixture recipes prove Docling/OCR
accuracy. No Docling/OCR package or model was installed or executed for this
research. No real evidence artifact was persisted by this work.

Package metadata, tagged API definitions and publisher artifact indexes below
were inspected. Proposed pins must be resolved, installed and tested in the
approved Python 3.12 Linux worker before dependency_versions.md calls them tested.
Main-branch implementation references are explicitly identified where a tagged
backend file was unavailable to the research browser.

## Proposed dependency boundary

| Component | Proposed choice | Verification still required |
|---|---|---|
| Docling SDK | docling-slim[format-pdf,models-local,feat-ocr-rapidocr-onnx]==2.134.0 | Frozen project lock, import/conversion smoke test and installed distribution/source identity |
| Core document shapes | docling-core==2.98.0 | Typed adapter behavior and provenance/geometry parity |
| PDF parser | docling-parse==7.22.1 | Actual worker wheel/load and native parser frame calibration |
| One OCR engine | rapidocr==3.9.2, ONNX backend | Selected English artifacts, offline execution and transcription measurements |
| CPU runtime | onnxruntime==1.30.0 | Actual CPU execution provider, worker load and selected model compatibility |
| Layout/table inference | torch==2.13.0 and torchvision==0.28.0 from the explicit CPU index; exact docling-ibm-models pin after resolution | Compatible CPU wheels, license inventory, model load and full locked transitive dependencies |

The official 2.134.0 source names the SDK distribution docling-slim; the ordinary
docling package is a metapackage. This modular choice preserves Docling and the
same SDK while limiting required features to this phase. It requires
docling-core>=2.98.0 and docling-parse>=7.22.1. Avoid the models-onnxruntime extra:
on Linux/Windows its requirements select onnxruntime-gpu. Select the CPU Torch
wheel source explicitly instead of accepting an incidental CUDA dependency set.
The final lock, wheel hashes and image digest are measured implementation records,
not facts established by these candidates.

Sources: [versioned Docling package definitions](https://raw.githubusercontent.com/docling-project/docling/v2.134.0/pyproject.toml),
[Docling 2.134.0 metadata](https://pypi.org/project/docling/2.134.0/).

Publisher metadata provides Python 3.12 Linux x86_64 wheels for docling-parse 7.22.1
and ONNX Runtime 1.30.0. The latter's Linux wheel requires glibc 2.28+; Windows amd64
and macOS 14+ ARM64 wheels are also available. RapidOCR 3.9.2 has a universal wheel.
These availability checks are not execution results on any of those platforms.
Docling code is MIT, RapidOCR code Apache 2.0 and ONNX Runtime MIT; model licenses must
be recorded separately.

Sources: [parser distribution](https://pypi.org/project/docling-parse/7.22.1/),
[RapidOCR distribution](https://pypi.org/project/rapidocr/3.9.2/),
[ONNXRuntime distribution](https://pypi.org/project/onnxruntime/1.30.0/).

## Proposed converter configuration

Use DocumentConverter/PdfFormatOption with InputFormat.PDF only, an explicit
StandardPdfPipeline and frozen PDF backend. The current converter default is
ThreadedDoclingParseDocumentBackend; inspect the installed version and name it
explicitly in adapter provenance. Accept only an application-owned source path or
stream, with the existing byte/page limits and an explicit timeout. Require the
expected page coverage, successful status and acceptable error diagnostics before
constructing a completed parse. PARTIAL_SUCCESS must not silently become a
completed artifact.

Source: [versioned converter API](https://raw.githubusercontent.com/docling-project/docling/v2.134.0/docling/document_converter.py).

Initial tuning configuration, not a measured selection:

- RapidOcrOptions: lang=["en"], backend="onnxruntime",
  mode=OcrMode.PDF_AWARE_LAYOUT_REGIONS, model_size="tiny", scale=3.0,
  text_score=0.5, use_det/use_rec/use_cls=True and print_verbose=False.
- PdfPipelineOptions: OCR and table structure enabled, parsed pages retained,
  explicit CPU/thread options, table cell matching enabled and an initial accurate
  TableFormer mode. Disable code/formula/picture enrichment, remote services and
  external plugins. Freeze the complete resolved configuration, including options
  that otherwise inherit defaults.
- Use native text where adequate and targeted OCR for inadequate/raster regions.
  Do not force full-page OCR routinely. The deprecated force_full_page_ocr flag,
  implicit language and default mode should not define the experiment.

English is an explicit single-language choice. The current RapidOCR adapter warns
when multiple languages are supplied, and an empty language defaults to Chinese.
Record any unsupported-language limitation rather than silently switching engines.

Sources: [versioned options](https://raw.githubusercontent.com/docling-project/docling/v2.134.0/docling/datamodel/pipeline_options.py),
[versioned RapidOCR stage](https://raw.githubusercontent.com/docling-project/docling/v2.134.0/docling/models/stages/ocr/rapid_ocr_model.py).

## Model acquisition, licensing and offline execution

Runtime/source review2026-10-07 also established these boundaries:
low-level TextCell rectangles retain all four reported corners. Assembled Docling
TextItems may have unknown OCR origin; their flag remains null rather than being
labelled native. Core2.99.0 can clamp exported provenance/table boxes internally;
the adapter cannot recover discarded coordinates. Retain reported assembly boxes
separately from low-level source rectangles and prefer the latter for exact
evidence. No source-frame calibration result is implied by these source findings.

Acquire only the selected layout, TableFormer and English ONNX RapidOCR models.
The generic downloader currently enables additional model families and multiple
OCR backend/language pairs by default. Pass explicit model selections or disable
every unneeded flag. If using docling-tools, verify the installed CLI help before
the acquisition command; its CLI extra is separate from the narrow SDK choice.

Set artifacts_path to the ignored model directory. The RapidOCR stage treats that
path as fully offline and fails for missing required artifacts/custom paths. Mount
the completed model directory read-only in the worker, enable applicable offline
environment options and demonstrate initialization/conversion without network
access. Do not give conversion a remote PDF URL or an opportunity to fetch models
implicitly.

Source: [official downloader implementation, main branch](https://raw.githubusercontent.com/docling-project/docling/main/docling/utils/model_downloader.py).

The artifact manifest must retain each model's publisher/repository, source URL,
immutable commit or resolved revision, filename, byte size, SHA256, applicable
license text/model card and acquisition time. Verify bytes during acquisition and
before worker use. Include config files, tokenizer/dictionary assets and any font
assets actually needed by the selected stage. Hash this complete manifest and
include its identity in the frozen adapter configuration/artifact provenance.

| Model family | Proposed source boundary | License evidence and remaining work |
|---|---|---|
| Layout | docling-project/docling-layout-heron at 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8 | Publisher model card identifies Apache 2.0; retain card/license and selected weights/config hashes |
| TableFormer | docling-project/docling-models at fc0f2d45e2218ea24bce5045f58a389aed16dc23, resolving v2.3.0 | Pinned README declares CDLA-Permissive 2.0; repository also carries Apache 2.0 metadata, with code licensing separate; retain applicable model/license evidence |
| RapidOCR | RapidAI/RapidOCR versioned 3.9.2 artifact index, English tiny detector/recognizer plus classifier | Versioned ModelScope README and repository API declare Apache License 2.0; retain that declaration and upstream license text at acquisition |

Sources: [Heron model card](https://huggingface.co/docling-project/docling-layout-heron),
[TableFormer repository](https://huggingface.co/docling-project/docling-models),
[TableFormer loader, main branch](https://raw.githubusercontent.com/docling-project/docling/main/docling/models/stages/table_structure/table_structure_model.py),
[RapidOCR license](https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/LICENSE),
[PaddleOCR license](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE).

The RapidOCR 3.9.2 publisher index provides fixed ModelScope resolve/v3.9.2 URLs.
The following small-tier hashes remain a possible same-engine tuning comparison;
the subsequent preflight proposes tiny as the minimum initial CPU artifact set.
These are publisher declarations, not hashes measured from acquired model files:

| Selected artifact | Published SHA256 |
|---|---|
| PP-OCRv6_det_small.onnx | 090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f |
| PP-OCRv6_rec_small.onnx | 6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884 |
| ch_ppocr_mobile_v2.0_cls_mobile.onnx | e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c |

Source: [versioned publisher artifact index](https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/python/rapidocr/default_models.yaml).

### Completed metadata preflight, still no runtime test

Read-only follow-up inspected immutable Hugging Face revisions, large-file
pointers, the official CPU wheel dependency metadata and ModelScope's versioned
README/file metadata. Responses were read in memory; no package/model binary was
downloaded, no environment was installed and no model was executed.

| Required layout/table artifact | Publisher byte size | Publisher SHA256 expectation |
|---|---|---|
| Heron model.safetensors | 171658996 | 00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c |
| TableFormer accurate/tableformer_accurate.safetensors | 212758388 | 2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9 |

Acquire Heron's config.json, preprocessor_config.json and model card at its pinned
revision, and TableFormer's tm_config.json/model card plus selected accurate
weights at its pinned revision. Use resolve/<immutable-commit>/<path> URLs and
explicit file allowlists. Compute all small-file hashes on acquisition; do not
invent them from Git object identifiers. Pinning only a branch or tag is
insufficient even when a publisher large-file hash is available.

Sources: [Heron revision](https://huggingface.co/docling-project/docling-layout-heron/commit/8f39ad3c0b4c58e9c2d2c84a38465abf757272d8),
[Heron weight pointer](https://huggingface.co/docling-project/docling-layout-heron/raw/main/model.safetensors),
[TableFormer revision](https://huggingface.co/docling-project/docling-models/commit/fc0f2d45e2218ea24bce5045f58a389aed16dc23),
[TableFormer weight pointer](https://huggingface.co/docling-project/docling-models/raw/v2.3.0/model_artifacts/tableformer/accurate/tableformer_accurate.safetensors).

The smallest Docling-resolved English CPU candidate uses model_size="tiny", the
two PP-OCRv6 tiny ONNX models and the existing PP-OCRv4 mobile classifier. This
selection is supported by the inspected registry/API, not measured OCR quality.
All URLs below share https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/.

| Relative artifact path | Publisher bytes | Publisher SHA256 expectation |
|---|---|---|
| onnx/PP-OCRv6/det/PP-OCRv6_det_tiny.onnx | 1829618 | f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5 |
| onnx/PP-OCRv6/rec/PP-OCRv6_rec_tiny.onnx | 4489813 | e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b |
| onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx | 585532 | e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c |
| paddle/PP-OCRv6/rec/PP-OCRv6_rec_tiny/ppocrv6_tiny_dict.txt | 27156 | c5cbe34ef40c29c4df07ed012bf96569cb69a2d2a01a07027e9f13cb832bd9cd |
| README.md | 1140 | 3dc91bb3cb667df783178917d69b38bfabb8c935596f34243a1c9f0d36916b6e |

The ONNX recognizer's character dictionary is embedded according to the inspected
Docling/RapidOCR source. Check that actual metadata and record its charset identity
when acquiring the file. A separate dictionary is not required when that key is
present; the matching dictionary above is an explicit provenance/fallback asset.
If it is used, freeze its path and validate output-class alignment. Never permit
a missing dictionary to fall back to the unrelated default Chinese keys download.
The three model files total 6904963 bytes before manifests/license/dictionary.

ModelScope's versioned README and model API identify Apache License 2.0. Retain
the versioned declaration plus license text and hashes, and verify expected model
hashes before use. Fonts are lazy visualization assets in the inspected source;
do not call RapidOCR visualization or acquire its default FZYTK.TTF for production
parsing. Use original PDF highlights for QA. If a future visualization needs a
font, choose and document a licensed, explicitly local font separately.

Sources: [versioned model license declaration](https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/README.md),
[repository license metadata](https://www.modelscope.cn/api/v1/models/RapidAI/RapidOCR),
[versioned repository file metadata](https://www.modelscope.cn/api/v1/models/RapidAI/RapidOCR/repo/files?Revision=v3.9.2&Recursive=true),
[recognizer dictionary handling](https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/python/rapidocr/ch_ppocr_rec/main.py),
[ONNX dictionary metadata handling](https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/python/rapidocr/inference_engine/onnxruntime/main.py),
[lazy font handling](https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/python/rapidocr/utils/vis_res.py).

### Proposed worker-only optional extra and CPU index

Official release instructions pair torch 2.13.0 with torchvision 0.28.0. The CPU
index exposes cp312-cp312-manylinux_2_28_x86_64 wheels for both. Read wheel metadata
confirms torch 2.13.0+cpu has no CUDA/NVIDIA/Triton runtime package requirement;
its non-optional requirements are filelock, typing-extensions, setuptools, sympy,
networkx, jinja2 and fsspec. Vision0.28.0+cpu requires torch==2.13.0, numpy and
Pillow. Both metadata records support Python 3.12. Retain the wheel's bundled
license inventory: Torch now declares a compound SPDX license expression rather
than a single simplistic license label. No load/inference compatibility was tested.

| CPU wheel | Publisher SHA256 expectation |
|---|---|
| torch-2.13.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl | 4ca4a9394b0c771238a4f73590fdbbc4debad85ed0fa63d026ae1b085da7d6e2 |
| torchvision-0.28.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl | b545d46f4d2f9d30381281cf22874bfe1d32a8a7b0ee8396fccde89f30c6a9d9 |

Sources: [official release pairs](https://pytorch.org/get-started/previous-versions/),
[Torch CPU wheel index](https://download.pytorch.org/whl/cpu/torch/),
[Vision CPU wheel index](https://download.pytorch.org/whl/cpu/torchvision/),
[Torch CPU metadata](https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl.metadata),
[Vision CPU metadata](https://download-r2.pytorch.org/whl/cpu/torchvision-0.28.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl.metadata).

An optional parsing extra keeps native API/default tests light while installing
the authorized parser in the worker. uv supports extra-specific sources and
platform markers, with explicit indexes restricting alternate sourcing to named
packages. Proposed pyproject shape below is illustrative and has not been locked
or tested; exact remaining inference pins belong to the actual resolution:

```toml
[project.optional-dependencies]
parsing = [
  "docling-slim[format-pdf,models-local,feat-ocr-rapidocr-onnx]==2.134.0; sys_platform == 'linux' and platform_machine == 'x86_64'",
  "docling-core==2.98.0; sys_platform == 'linux' and platform_machine == 'x86_64'",
  "docling-parse==7.22.1; sys_platform == 'linux' and platform_machine == 'x86_64'",
  "rapidocr==3.9.2; sys_platform == 'linux' and platform_machine == 'x86_64'",
  "onnxruntime==1.30.0; sys_platform == 'linux' and platform_machine == 'x86_64'",
  "torch==2.13.0; sys_platform == 'linux' and platform_machine == 'x86_64'",
  "torchvision==0.28.0; sys_platform == 'linux' and platform_machine == 'x86_64'",
]

[tool.uv.sources]
torch = [{ index = "pytorch-cpu", extra = "parsing", marker = "sys_platform == 'linux' and platform_machine == 'x86_64'" }]
torchvision = [{ index = "pytorch-cpu", extra = "parsing", marker = "sys_platform == 'linux' and platform_machine == 'x86_64'" }]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
```

Resolve once into the project's authoritative lock. Native default sync omits
extras; the Linux worker uses a frozen sync with --extra parsing and excludes dev
groups as intended. Runtime parsing checks explicitly run in that worker, while
native tests verify contracts/orchestration without importing heavy optional
libraries eagerly. Do not use --no-sources or a separate untracked pip install;
both would evade the selected CPU source. The architecture markers describe the
approved/tested target only and do not establish ARM64/macOS parsing support.

Sources: [uv PyTorch integration](https://docs.astral.sh/uv/guides/integration/pytorch/),
[uv optional dependencies and markers](https://docs.astral.sh/uv/concepts/projects/dependencies/),
[uv frozen syncing and optional extras](https://docs.astral.sh/uv/concepts/projects/sync/).

## Canonical geometry and backend calibration

The existing contract stores unrotated PDF points with bottom-left origin,
original media/crop boxes and rotation 0/90/180/270. Page indices are zero-based;
PDF viewer page numbers are index+1. Read original MediaBox, CropBox and Rotate
through the existing pypdf dependency; do not substitute Docling's crop-based page
dimensions for original media dimensions.

A Docling bbox with BOTTOMLEFT origin does not establish its rotation or offset
frame. The examined PDFium backend transforms raw PDF rectangles into a rotated
display frame. The parser's geometry retains angle/media/crop information, while
Docling backend processing also changes coordinate origins. Main-branch backend
inspection is a hypothesis source, not proof of the installed 2.134.0 frame.
Inspect the pinned backend/low-level parsed-page APIs, retain their raw dimensions
and boxes, and calibrate one explicit frame transform against original PDFs.

Sources: [PDFium backend, main branch](https://raw.githubusercontent.com/docling-project/docling/main/docling/backend/pypdfium2_backend.py),
[Docling parse backend, main branch](https://raw.githubusercontent.com/docling-project/docling/main/docling/backend/docling_parse_backend.py),
[versioned parser geometry](https://raw.githubusercontent.com/docling-project/docling-parse/v7.22.1/docling_parse/pdf_parser.py),
[core page geometry, main branch](https://raw.githubusercontent.com/docling-project/docling-core/main/docling_core/types/doc/page.py).

For a demonstrated crop-relative, rotated-display, bottom-left frame only, the
following inverse is a mathematical candidate. Let the actual visible crop
intersection begin at (X0,Y0), with unrotated width w and height h; (dx,dy) is a
display-frame point. The installed backend may require a different transform.

| PDF rotation | Candidate raw PDF point |
|---|---|
| 0 | (X0+dx, Y0+dy) |
| 90 | (X0+w-dy, Y0+dx) |
| 180 | (X0+w-dx, Y0+h-dy) |
| 270 | (X0+dy, Y0+h-dx) |

For a verified top-left display frame, first flip y using its display height.
Transform all four rectangle corners before taking min/max. Test nonzero and
negative origins, crop offsets and all four rotations; retain the input frame,
transform identifier and raw output in diagnostics. Do not infer crop/media frame
from whether a bbox fits, rotate twice or silently clamp bad coordinates. An
invalid/unavailable transform makes exact geometry unavailable until resolved.

## Exact text, structure and unavailable evidence

Retain backend TextCell.orig together with processed text, backend index/item
reference, raw geometry, from_ocr and actual available OCR score. Preserve blank
and dash cell text. Preserve table row/column indices and spans, header flags and
cell mappings before constructing the canonical artifact; model-supplied semantic
period/unit/basis interpretation does not become accepted financial context here.

Build page-local stored blocks and exact Unicode code-point spans from the text
actually retained. Validate every quote against its stored block and every cell
against its stored source membership. Markdown export, dehyphenated display text
or a page-wide citation cannot establish those offsets. Cross-page support uses
separate page-local evidence records. OCR text remains a transcription with its
source image/geometry/provenance; exact stored quotation does not prove OCR truth.

There is an upstream report of merged/dehyphenated provenance charspans exceeding
text length in an earlier release. Add that regression scenario and check actual
2.134.0 behavior; this plan does not assert that release still contains the bug.
Invalid offsets produce explicit diagnostics/unavailable evidence, not fabricated
replacement spans.

Source: [upstream provenance report](https://github.com/docling-project/docling/issues/4217).

Optional cell boxes must stay missing when the parser supplies none. Do not copy
a whole table box and call it exact cell geometry. Preserve incomplete structure
for diagnostics and route unsupported/ambiguous evidence for later review; it
must not enter exact supported evidence silently. Missing OCR scores remain
unavailable. Native confidence defaults and aggregate quality signals are not
measured OCR confidence or calibrated correctness; record signal provenance and
reject non-finite values rather than inventing a confidence result.

The adapter-owned structured artifact should retain source hash, adapter/package
versions, backend identity, complete configuration/model-manifest hashes, original
page geometry, source-item mappings, exact text/cells, native/OCR status and
diagnostics. Hash deterministic serialization separately from volatile run time,
latency and timestamps. Use the existing immutable ParseVersionRecord and declared
counts; job progress/status stays in M1.2 jobs, and M1.4 will persist a complete
artifact and evidence atomically. This plan adds no accepted facts or publication.

## Acceptance and measured benchmark record

Implementation may begin after M1.2 runtime acceptance. M1.3 acceptance requires:

1. Actual locked worker imports/model loading and native, table and raster parsing
   with the single configured RapidOCR ONNX CPU engine. Record packages, image,
   CPU/thread settings, selected execution provider and all artifact hashes.
2. Native/OCR quality checks on authored fixtures: exact retained Unicode text,
   row/column/header mappings, blank/dash preservation, finite score handling,
   missing boxes and honest failed/partial/empty/garbled OCR diagnostics.
3. Four-rotation and crop-offset calibration against the original rendered PDF,
   including negative/nonzero media/crop origins and text/table highlights. All
   transforms must have measured fixture evidence before being enabled generally.
4. A real Premier Energies benchmark using the acquired three-page public source.
   Manually inspect retained text, changed table/context examples and rendered
   highlights. State actual source hash, pages/snippets inspected, reference
   transcriptions, errors, native versus OCR use, counts, runtime and memory.
   If this source lacks a raster/native/table category, report that limitation and
   use the labelled synthetic fixture for the missing engineering check; do not
   claim the real filing supplies it.
5. Tune only bounded settings of this one engine, then freeze the selected config
   and artifact hashes. Record numeric transcription/header/context mistakes,
   missing geometry and failure handling. No fictional accuracy improvement,
   calibrated confidence, gold corpus or research effectiveness is established.
6. Independent adapter review and relevant project checks. M1.4 acceptance remains
   separate: atomic persisted evidence plus authenticated full/range source access
   and visually verified persisted highlights are still required for M1A closure.

Record actual commands, sample/count denominators, comparison settings, latency,
model acquisition/license results and remaining limitations in the phase record.
Synthetic fixture results establish engineering behavior only. M1B evidence gates,
review, accepted observations, amendments and publication remain outside this plan.
