# M2 numerical source intake

Two existing seed companies have a small source-review packet in
`data/analysis-source-review.json`. It contains official URLs, immutable download
hashes, cover/listing dates, CINs, table/context page locators and four raw
revenue amounts. Original PDFs, text extracts and page PNGs remain in the ignored
local `.cache/analysis-source-review/` directory. The original M1 manifest and
published corpus are unchanged.

This packet is operator preparation. It has no accepted facts, M1 evidence IDs,
metric IDs, canonical company IDs or human reviewer assertion. It cannot be
submitted as the typed M2 acceptance plan or used as an application fact source.

## Inspected sources

The sources are the [Premier Energies prospectus on SEBI](https://www.sebi.gov.in/filings/public-issues/aug-2024/premier-energies-limited-prospectus_86360.html)
and [Waaree Energies prospectus on SEBI](https://www.sebi.gov.in/filings/public-issues/oct-2024/waaree-energies-limited-prospectus_91613.html).
Both original PDFs were downloaded, hashed and cross-checked with pypdf 6.19.0;
the complete relevant table/context pages were rendered with bundled Poppler and
visually inspected. No PDF was rewritten and no parser/job was started.

| Source | Cover date | SEBI listing date | Financial table | Fiscal/basis context |
|---|---|---|---|---|
| Premier Energies | 29 August 2024 | 30 August 2024 | PDF page 30, index 29, printed 26 | PDF page 20, index 19, printed 16 |
| Waaree Energies | 23 October 2024 | 23 October 2024 | PDF page 99, index 98, printed 95 | PDF page 19, index 18, printed 15 |

These locators were checked against the downloaded PDFs. Cover/listing dates and
server URL folders do not establish publication/effective dates. Waaree's PDF
is currently linked from a February 2025 storage URL despite its October 2024
cover. Keep publication/effective dates unknown until supported separately.

The following are **unaccepted source-review amounts**, in the stated INR million
unit and restated consolidated context. Preserve original comma grouping.

| Company | Row | Year ended 31 March 2023 | Year ended 31 March 2024 |
|---|---|---|---|
| Premier Energies | Revenue from operations | `14,285.34` | `31,437.93` |
| Waaree Energies | Revenue from operations | `67,508.73` | `1,13,976.09` |

The quarter columns next to these annual columns must remain distinct. No
comparison, normalized authoritative value or accepted full duration is produced
by this review. The packet alone does not cover every acceptance category;
both tables use the same unit.

## Producer dependency before M2 can use them

The table headers specify year ends. Each filing separately defines its fiscal
year as the 12-month period beginning on 1 April of the preceding calendar year.
The frozen M1 numerical gate deliberately leaves an end-only duration's start
unset and requires review (`backend/src/regintel/validation/quantity.py`). M2
requires a complete supported duration. A visual reader's interpretation does
not bypass either gate.

The next producer task is to obtain exact M1 evidence/table/cell/header records
for the original PDFs and verify supported period/basis links, including any
relevant fiscal-definition evidence. Locate explicit complete date-range support
or address a genuine producer capability gap within an authorized M1 change.
Do not fill a missing start, fabricate cells/spans or waive mandatory checks in
M2. The selected table/context pages have now been sampled through the existing
pinned Docling environment; see [original-page preparation](M1_NUMERICAL_SOURCE_PAGES.md).
This does not establish a full-filing parse or a passing M1 numerical gate.
Neither document is uploaded, accepted or published by the preparation tool.

Resolve company identities through the verified source CINs and approve a common
metric definition through M1. Matching labels alone do not establish semantic
equivalence. Preserve filing/version history and use the existing validation,
review, acceptance and publication interfaces. The new Premier prospectus is
dated 29 August; the existing addendum names an RHP dated 20 August. No parent or
blanket supersession effect is inferred between them.

Keep the manual-testing M1 corpus unchanged while preparing this work. After a
supported numerical corpus is actually published and expectations are reviewed,
fill the independent [M2 acceptance plan](M2_ACCEPTANCE.md) with its real IDs.
The current real plan remains empty and reports `BLOCKED`.
