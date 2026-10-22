# Complete-original parser benchmark

This implements a bounded experiment under the approved
[numerical producer prerequisite](M2_NUMERICAL_PRODUCER_PLAN.md). The existing
worker, parser descriptor, source files and original M1 database are unchanged.
The experiment has no database, authentication, queue, model-provider or
publication path. It runs the existing pinned Linux parser and local models.

## Why measure the whole original

Successful single-page samples do not establish whole-filing conversion. The
existing 180-second configuration was exercised against the intact 558-page
Premier Energies prospectus. It returned `partial_success`, five processed pages
and 554 SDK errors after 235.388 seconds of conversion; initialization took
30.590 seconds. Peak process RSS was 3,377,892 KiB. The container had two CPUs,
4 GiB memory, no swap and a 768 MiB temporary filesystem. This is one engineering
sample, not a performance distribution or financial-extraction accuracy result.

The assembled SDK document still contained 558 page metadata entries. Those
entries cannot prove processing coverage: the actual result contained only five
pages. The reusable benchmark checks successful status, no errors, exact ordered
original page numbers, retained native page data and complete assembled page
membership independently. Sparse pages cannot be renumbered into a full filing.

## Explicit experimental configuration

`regintel.parsing.full_filing` first creates and verifies the frozen converter
against the selected baseline descriptor. It creates a fresh converter by
copying its PDF options, changing only the explicitly supplied document timeout.
The actual resolved options must equal the baseline except for that timeout.
The original converter/options are left intact. An integer timeout from 181 to
3,600 seconds is required; there is no new default worker setting.

The resulting SDK configuration and processing descriptor have their own hashes.
A separate `full-filing-timeout-experiment-1` profile binds the baseline,
extension code, timeout and selected identities. The resolved runtime descriptor
does not replace `data/parser-runtime-config.json`. The profile is an experiment
record, not an approval or signature. Old preparations/observations retain their
original configurations. A new configuration cannot silently reuse preparation
records from the old SDK fingerprint.

The converter/options API was checked against the
[official pinned Docling 2.134.0 source](https://github.com/docling-project/docling/blob/v2.134.0/docling/document_converter.py).
The actual offline initialization additionally verifies package, backend, model
and resolved-option hashes against the selected baseline.

The extended experiment uses 900 seconds, four CPUs and 4 GiB memory. Because the
CPU cap also differs, the two measurements cannot isolate a timeout-only speed
effect. Exact results and limitations are recorded in
`data/full-filing-validation-report.json`; source PDFs, raw captures and console
logs remain ignored local artifacts.

That extended process exited137 after initializing the pinned configuration.
It did not save `raw.json` or a final script report. The retained profile proves
initialization, not conversion completion. Its termination cause is unconfirmed:
the automatically removed container is absent and historical Docker events were
unavailable after the engine session restarted. Exit137 alone does not prove an
out-of-memory kill. The measured report retains a separate external exit
observation; missing page/error/runtime/RSS results are not invented. Future
experiments must retain the owned container's terminal state before removal.

## Run in the existing offline image

Use the existing `regintel-ingestion:local` image with UID/GID10001, a read-only
root filesystem, no network, dropped capabilities, no new privileges, explicit
CPU/memory limits and writable temporary storage. Mount this checkout read-only
at `/code`, approved originals read-only at `/sources`, and existing pinned models
read-only at `/models`. Mount only the ignored experiment output directory
writable at `/outputs`. Keep the model path `/models` to match the selected
baseline's resolved options. No worker or broker is started.

Inside that container:

```bash
PYTHONPATH=/code/backend/src python /code/scripts/benchmark-full-filing.py \
  --source /sources/premier-energies-prospectus-20240830.pdf \
  --source-sha256 aeac8f5598627bf5704d0ae714c4ec536570f320cbb552f682a29ed3d3fc14ca \
  --models /models \
  --baseline-config /code/data/parser-runtime-config.json \
  --timeout-seconds 900 \
  --output-dir /outputs/fresh-complete-original-experiment
```

Explicit offline environment flags and container networking restrictions remain
required. The script also denies Python socket connects and verifies the original
hash before and after conversion. Its connect counter does not audit native DNS
or prove that the parser's transcription is correct.

The output folder must be fresh and absolute; an existing folder is untouched.
The script retains `profile.json`, `configuration.json`, `raw.json` and
`report.json`. JSON is streamed into a fresh file, with an explicit 512 MiB raw
capture bound. An over-bound partial file is diagnostic failure, never a complete
capture. This experimental raw-data limit does not increase M1's existing 64 MiB
artifact or upload limits. Conversion/SDK failures use a fixed public diagnostic
to avoid exposing untrusted filing text.

Exit0 means complete SDK capture coverage; exit2 means incomplete SDK capture;
exit1 means failure. None of these outcomes creates an M1 artifact, evidence ID,
accepted fact, reviewer decision or corpus publication. The current complete
adapter, source/evidence gates and actual review remain necessary.

## Native words and existing M1 evidence

The retained real page captures also allow a read-only check of the current
binding prerequisite. Native `parsed_page.word_cells` and the final SDK `cells`
are separate outputs. Final cells can combine multiple native words. A native
word cannot be called an existing public word-evidence record just because a
larger cell contains its text. The exact-word binding still requires the actual
original text, corners and geometry; no substring box or evidence ID is invented.

The validation report records the measured availability for the four retained
real context inspections. This diagnostic uses their exact original capture
hashes and does not execute a real positive binding or manufacture a complete
artifact. Any missing support needs an explicitly versioned producer/evidence
extension before acceptance; the existing mandatory gates continue to apply.

Next use the measured whole-source result to complete a reproducible producer
path, preserve exact native and table context support, then perform mandatory
validation, actual review and immutable publication in isolation. Real M2
acceptance remains blocked until genuine published numerical inputs and
independently reviewed expected results exist. Quotes stay unavailable.

Final native verification passes2,178 backend cases with six existing Windows
platform skips and579 database cases deselected (577.200s JUnit), including the
33 new authored controls. Ruff checks240 files, strict mypy checks158 sources,
and nine generated-contract/fixture checks pass. Both portable check runners now
include this CLI. No database or frontend implementation changed, so their live
suites were not repeated for this checkpoint. The prior binding commit passes
all three exact-source GitHub jobs; that result does not verify this new code.
