# Import retained native source evidence into M1

The `regintel-native-intake` command connects the existing offline native/page
capture tools to the existing M1 source store, numerical page records and native
producer. It replays captures without importing Docling or running models on the
native host. The approved Linux capture environment remains responsible for
obtaining the complete bank and selected contextual SDK pages.

This is source preparation and evidence persistence. It does not create a
financial context draft, gate, candidate, accepted observation, amendment effect
or corpus publication. Company labels in upload metadata are unapproved intake
labels. Financial units, periods, basis and identities still need source support
and their existing independent approvals.

## Select the actual files

Prepare the intact original and the retained outputs described in
[native context evidence](M1_NATIVE_CONTEXT_EVIDENCE.md) and
[original-page preparation](M1_NUMERICAL_SOURCE_PAGES.md). Select the exact parser
runtime descriptor belonging to those contextual captures. Do not substitute a
different SDK/model/package fingerprint or edit a descriptor to make it match.

Create an ignored local plan, for example `.cache/native-intake/plan.json`.
Every selected file needs an absolute path and its actual lowercase SHA-256.
`Get-FileHash -Algorithm SHA256 -LiteralPath <path>` computes that hash on Windows.
The complete bank must retain `manifest.json` and every referenced
`page-NNNN.json` in its original directory. `raw_capture` selects the actual raw
SDK JSON, rather than a prepared preview or an exported application fixture.

The following is a shape illustration; replace paths and all hash placeholders
with the selected installation's real files. No approval is expressed by it:

```json
{
  "schema_version": "native-intake-plan-1",
  "source": {"path": "D:\\RegIntel\\.cache\\intake\\original.pdf", "sha256": "<actual original SHA-256>"},
  "parser_configuration": {"path": "D:\\RegIntel\\data\\parser-runtime-config.json", "sha256": "<actual descriptor SHA-256>"},
  "native_manifest": {"path": "D:\\RegIntel\\.cache\\intake\\bank\\manifest.json", "sha256": "<actual manifest SHA-256>"},
  "metadata": {
    "company_name_raw": "<source intake label>",
    "document_type": "PROSPECTUS",
    "source_url": null,
    "published_on": null,
    "declared_parent_filing_version_id": null
  },
  "context_pages": [
    {"pdf_page": 1, "raw_capture": {"path": "D:\\RegIntel\\.cache\\intake\\page-1\\raw.json", "sha256": "<actual raw capture SHA-256>"}}
  ]
}
```

Keep context pages unique and increasing, using **one-based physical PDF pages**.
Select one to 32 pages. The command also enforces the existing original limit of
64 MiB/2,000 pages, the selected parser's own smaller limits, a 2 MiB manifest,
4 MiB native page records/1 GiB total bank and 64 MiB per contextual capture.
Contextual input files together are capped at 128 MiB; the plan at 256 KiB.
Relative paths, links/junctions, nonregular files, duplicate object keys, changed
hashes and unsupported source geometry fail. Existing native/context rules require
unrotated full media/crop boxes at origin zero for selected evidence pages.

Do not infer publication/effective dates from a cover, a URL folder or a download
date. Leave unknown metadata null. Reusing an already uploaded original requires
exactly the same upload metadata; a conflicting label/date/declared parent cannot
silently rewrite it.

## Check, then import

Use the current integration checkout and its configured Python environment.
From that checkout on Windows:

```powershell
$project = (Get-Location).Path
$plan = Join-Path $project '.cache/native-intake/plan.json'
.\backend\.venv\Scripts\python.exe -m regintel.parsing.intake_cli check --plan $plan
```

`check` does not need credentials or a running database. It verifies every native
page, the original source and selected contextual bridge and returns a
`PREPARATION_ONLY` JSON receipt. Temporary in-memory identities used for replay
are discarded and never written or presented as accepted evidence. Exit zero
means source preparation passed; `acceptance_eligible` remains false.

Start the existing data services and apply the installation's documented
migrations through migration 14 or later. For the current shared numerical
publication/review workflow, follow its migrations through 22 and existing setup
instructions. Do not regenerate credentials or reuse another laptop's records.

```powershell
.\backend\.venv\Scripts\python.exe -m regintel.parsing.intake_cli import --plan $plan --project-root $project --env-file (Join-Path $project '.env') --auth-env-file (Join-Path $project '.env.auth') --username admin
```

Use the installation's actual administrator username. The command prompts for its
existing password without echo; passwords/tokens cannot be passed as arguments.
A missing private terminal fails instead of falling back to echoed input. It
does not seed accounts or change credentials. A project-local entry point named
`regintel-native-intake` is also installed by the normal locked environment sync.
No new dependency, required setting, migration, worker rebuild or port is added.

Import rechecks current administrator authority, repeats preparation, copies the
unchanged original through content-addressed storage, retains page captures and
seals via `NativeM1Producer`. The result is `SOURCE_EVIDENCE_SEALED`, with the
actual filing job/parse and capture IDs, still `acceptance_eligible: false`.
No source text, credential, token or local path appears in successful receipts or
the sanitized `INTAKE_FAILED` response.

## Repeat, recover and continue review

These explicit native jobs belong to the calling command. They have **no Celery
dispatch intent**; the ordinary upload/worker path retains its default behavior.
An existing job cannot change dispatch ownership. Concurrent same-source imports
seal one job/parse. Repeat success requires the same captures, artifact,
configuration and complete retained native page bytes, not merely a terminal job
state. A different capture for an already sealed source/configuration conflicts;
it cannot replace historical evidence.

Source upload, page retention and atomic parse sealing are distinct durable
checkpoints. Interrupted queued/running imports can resume by rerunning the exact
plan. Invalid preparation writes no source/database identity. Later failures may
retain an immutable source/capture checkpoint; they do not leave a partially
sealed parse or accepted facts. A terminal failed/source-verification job cannot
be relabelled successful by retrying. Inspect the retained job and correct the
actual prerequisite; do not alter frozen fingerprints or discard history.

Save the returned filing/parse/capture IDs locally. The next steps are exact
context drafting, approved issuer/metric/policy support and the
[bound numerical gate](M2_BOUND_NUMERICAL_GATES.md), followed by
[administrator review, acceptance and common publication](NUMERICAL_ADMIN_WORKFLOW.md).
The historical numerical queue discovers gates only after that gate work exists.
This command alone does not populate it or seed a teammate's clone.

For company names represented by separate native words, the
[native company identity profile](NATIVE_COMPANY_IDENTITY.md) now provides the
existing administrator registry endpoint with explicit word/heading support.
That additional workflow requires migration 23 and an actual reviewed decision;
intake does not perform it automatically.

See the [validation report](../data/native-source-intake-validation-report.json)
for measured results and source fingerprints. Authored blank-PDF declarations
exercise engineering integrity and authorization, never real-filing accuracy,
human approval, gold annotation or financial performance. Four actual numerical
inputs, real amendment acceptance, seven M3 learning reviews and final module/
held-out/fresh-clone acceptance remain separate work. Runtime quotes remain
unavailable by the user's decision.
