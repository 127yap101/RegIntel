# Run, inspect and pause RegIntel

## Published questions and exact source excerpts (M1.11)

Start the configured native API/frontend with the commands below, sign into
the published filing explorer and select Premier Energies. Under **Find evidence
in filings**, ask **What does the filing disclose about an initial public
offering?** The result preserves the complete conditional source statement.
**Source 1 · page 3** opens its hash-verified original PDF and evidence region.

The question stays pinned to the applied corpus/history/date view and selected
company. Four search methods support the controlled retrieval comparison; the
semantic baseline deliberately omits company/period/basis metadata filters.
Published-corpus and active/history boundaries always remain. The default hybrid
method includes bounded related disclosures. Errors are explicit; changing
methods requires a new request. Results are labelled verbatim source excerpts,
with no generated conclusion or automatic reconciliation of conflicts.

The real corpus still contains one narrative and no accepted numeric values or
corporate relations. Unsupported topics, missing numeric context, unknown date
support and a context budget too small for complete support return unavailable.
**Retrieval details** shows the corpus, method and actual context-token budget.
Each question clears prior source/answer state; signing out clears private state.

Authenticated `POST /v1/retrieval` and `POST /v1/answers` are available in the API
explorer. Their schema supports explicit company/complete period/basis filters,
one/two-hop controls, top-k/context budgets and deterministic numeric lookups
with exact metric/unit/currency/ownership context. Lookup returns an accepted
Decimal value with its inputs; cross-fact formulas remain M2 work. No Gemini
provider or paid call is used. M1.12 administrative review UI remains later work.

See [M1.11 implementation/verification](M1_11_RETRIEVAL_PLAN.md) and
[current state](../CURRENT_STATE.md) for the checkpoint and measured limits.

M0/M1A, entity resolution, bounded candidates, text validation/staged reviews,
durable worker recovery and reviewed corpus publication are implemented.
The frontend includes a read-only published filing explorer and API liveness. Ingestion,
exact evidence/PDFs, entity decisions, unaccepted candidate runs and staged
validation/review audits are available
through the backend API. Company search, reviewed disclosures, directed corporate
relations and exact source pages can now be inspected after sign-in. Financial
comparison/profile, retrieval/Q&A and administrator review workflows remain later work.

## Inspect published filings in the browser

Use the installed-app commands below, then open the frontend and sign in under
**Published filing explorer** with an existing learner or administrator account.
Generated credentials remain privately in the machine's ignored `.env.auth`.
The browser keeps its bearer token in memory only; sign out when finished.

The explorer pins the current published corpus on sign-in. Select **PREMIER
ENERGIES LIMITED**, read the complete conditional proposed-IPO disclosure, then
choose **Inspect source 1**. The real proof opens original page 3, checks its hash
and overlays its persisted evidence region. Exact block-character support is
listed below the scrollable page; the region is not a character-level box.
The actual corpus has zero corporate relation observations, so the empty
corporate graph is explicit. The missing parent and unknown date remain visible
limitations. Applying a date returns unavailability; it does not invent a result.

Use **Include accepted history** or supply an explicit published corpus ID when
needed. **Apply view** clears the prior selection. Revoked/expired login clears
private results. Another machine must restore its own ignored sources/data and
use its actual corpus/company IDs; Git contains code/metadata, not this database.
See [M1.10 measured verification](../data/published-reads-validation-report.json).

## M1.9 published corpus

Reviewed publication, immutable history/effects and versioned graph/vector/lexical
projections are verified. Actual published corpus ID:
`614d7861-3f8f-4d5c-a9e5-d7423c2aba58`. It contains one conditional Premier narrative,
with unresolved parent/effects 0. Primary migrations 1–11 are applied. Hosted
Windows/Ubuntu and all 469 database checks pass; the native storage setup-error
and successful 7-case retry are disclosed in the [measured report](../data/publication-validation-report.json).

The native bootstrap now selects entities+publication. On a new machine, acquire
the pinned ignored BGE files with `python scripts/acquire-embedding-model.py`
from the configured backend environment before running publication. No weights
or original PDFs are stored in Git. The approved worker needs no M1.9 rebuild.

Administrators can create, read, publish and rebuild a corpus under `/v1/admin/publication/builds` in the API explorer. A
published corpus can be read at `GET /v1/corpora/{id}` with a current login;
`historical=true` preserves accepted history, and an unsupported `as_of_date`
returns explicit temporal unavailability. Obtain this machine's actual corpus
ID from the measured publication report. The M1.10 explorer uses published
company/fact/graph reads and corpus/observation-scoped learner source access.
Unscoped original evidence/PDF routes remain administrator-only. Review UI is
later work. See [publication operating contract](M1_9_PUBLICATION_PLAN.md).

## Inspect the saved result without starting services

- [Current state](../CURRENT_STATE.md)
- [Measured evidence verification](../data/evidence-validation-report.json)
- [Measured entity verification](../data/entity-validation-report.json)
- [Measured candidate verification](../data/candidate-validation-report.json)
- [Measured validation/review verification](../data/validation-review-report.json)
- [Measured processing/recovery verification](../data/processing-recovery-report.json)
- [Measured publication verification](../data/publication-validation-report.json)
- [Measured published reads/browser verification](../data/published-reads-validation-report.json)
- [Measured retrieval/source-answer verification](../data/retrieval-validation-report.json)
- [Source manifest](../data/manifest.json)
- Persisted CIN highlight: `D:/RegIntel/.cache/evidence-qa-7ce9c9a9d4404e6bae69c6b38385c682/cin-detail.png`

The real Premier job is `PARSED`, with one attempt, three source pages and 878
exact text evidence records. Known OCR/table/currency limitations are recorded;
the earlier parser records alone do not constitute financial acceptance. M1.9 now separately publishes the one reviewed conditional narrative described above.

## Run the installed app

Open Docker Desktop and wait for its Linux engine to run. These commands reuse
the installed toolchain and data services. Reading persisted records does not
require a parser worker build. New parsing/recovery work must follow the frozen
worker setup. The current rebuilt image includes the later stages in a separate environment while preserving the parser runtime.

In PowerShell terminal 1:

```powershell
Set-Location D:\RegIntel
.\scripts\compose.ps1 up
# Also start the private worker when submitting or recovering processing jobs:
.\scripts\compose.ps1 worker-up
.\backend\.venv\Scripts\regintel-api.exe --env-file .env --auth-env-file .env.auth
```

Leave that terminal running. In PowerShell terminal 2:

```powershell
Set-Location D:\RegIntel
.\.tools\pnpm\pnpm.cmd --dir frontend dev
```

Open:

- Frontend: <http://127.0.0.1:5173>
- API explorer: <http://127.0.0.1:8000/docs>
- Public process liveness: <http://127.0.0.1:8000/health/live>

In the API explorer, select **Authorize** and use the generated admin username
and password stored privately in `D:\RegIntel\.env.auth`. Leave optional client
credentials blank. The explorer obtains the bearer token using the configured
password flow. Use **Try it out** on:

- `GET /v1/filing-jobs/{job_id}` with `c81a8c48-2895-4c00-8d88-e45a99bd114e`.
- `GET /v1/evidence/{evidence_id}` with `a2491199-24e3-439f-bba6-3e380db8a28d`.
- `GET /v1/filing-versions/{filing_version_id}/source.pdf` with `295214b3-1c7a-44d4-8201-bf97a986a950`.
- `GET /v1/admin/entities/runs/{run_id}` with `407bc0fa-e97a-4d81-8c9f-126b682e83a7`.
- `GET /v1/admin/candidates/runs/{run_id}` with `6311f8bd-d49d-4fa8-b038-817205e73fff`.
- `GET /v1/corpora/{corpus_id}` with `614d7861-3f8f-4d5c-a9e5-d7423c2aba58` (current login).
- `GET /v1/published-corpus` and `GET /v1/companies` (current login).
- `GET /v1/companies/{company_id}/facts` and `/graph` with `581d1b0d-98fd-4a23-8e15-5574dac650a2`; pin `corpus_version_id` to the corpus above.
- `GET /v1/admin/publication/builds/{corpus_id}` with the same ID (administrator).
- `GET /v1/admin/validation/runs/{run_id}` with `97ec299b-f5e7-4043-9fec-e7c08473b6a9` for the final-code gate.
- `GET /v1/admin/processing/jobs/{job_id}` with `95ba9ce9-5f28-4187-a35b-3364415a838c` shows the verified recovered workflow.
- The same validation read with `f93660f2-c589-4cc5-af3d-031e896a4d3b` shows the original staged review.

Expected results: `PARSED`, an exact CIN quote with span/geometry/provenance, and
the original source PDF. Admin access is required; the learner role cannot read
these unpublished M1A sources. The final gate has one `REVIEW` result needing extractive confirmation. Its
original review is preserved on the earlier configuration. This validation read
shows staged eligibility; M1.9 separately accepts and publishes the one reviewed
conditional narrative described above. The recovered processing job is `SUCCEEDED`, generation2, with all three original output IDs. That status confirms processing only. Keep generated credentials local.

## Check implementation

Read-only schema status (expected applied 1–11, nothing pending):

```powershell
Set-Location D:\RegIntel
.\backend\.venv\Scripts\regintel-db.exe status --env-file .env
```

To rerun verification when desired, first stop the manual API/frontend with
**Ctrl+C** so ports 8000/5173 are free:

```powershell
.\scripts\run-checks.ps1
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py
```

The first runs backend/frontend/browser and static checks. The second requires
running Docker/PostgreSQL and creates/removes only its own disposable database.
Latest M1.11 local checks pass 1,902 backend tests with six disclosed Windows
skips, nine new disposable PostgreSQL/Neo4j cases, and the final complete frontend
release (238 unit tests, 14 Chromium tests, lint, strict types and build). The
earlier combined runner's two browser PDF-readiness timeouts are disclosed in the
[retrieval report](../data/retrieval-validation-report.json); the final frontend
run passes with two local workers and unchanged assertions/timeouts. The real
four-arm HTTP and original-PDF browser proofs pass without changing authoritative
data. M1.11 source `f57e2113fbd485e985e5e93e144ce15ebee42a02` is pushed and
exact-source [CI 38855802264](https://github.com/127yap101/RegIntel/actions/runs/38855802264) is SUCCESS
for Windows/Linux foundation and Linux data infrastructure. The complete database
command, fresh migrations 1–11 apply/replay, authentication and restart
persistence pass; per-test hosted counts are not inferred from inaccessible logs.

Previous M1.10 exact-source [CI 38755455205](https://github.com/127yap101/RegIntel/actions/runs/38755455205)
passes both Windows/Linux complete runners (1833/1835 backend, 225 frontend and
nine Chromium each), all 474 database tests, fresh migrations 1–11, authentication
and restart persistence. These are engineering checks; research effectiveness
remains unmeasured.

After a worker/infrastructure interruption, recover unfinished processing jobs
through the admin dispatch endpoint or the bounded operator command:

```powershell
.\backend\.venv\Scripts\python.exe -m regintel.processing.cli dispatch --env-file .env
```

Completed jobs are skipped. Frozen requests/inputs and committed stage results
are retained. Failed stale/configuration/authorization requests require a new
supported job; do not edit old rows. These checks have already passed and do not
need repeating merely to resume the checkpoint.

## Pause before sleep or shutdown

Stop manual API/frontend terminals with **Ctrl+C** if you started them. From the
project PowerShell terminal, stop the worker before its data services:

```powershell
Set-Location D:\RegIntel
.\scripts\compose.ps1 worker-stop
.\scripts\compose.ps1 stop
```

These actions retain the named volumes, database/evidence, source files and
models. Then quit Docker Desktop and use Windows **Start > Power > Sleep** or
**Shut down**. Closing the lid depends on your Windows power setting; choosing
Sleep explicitly avoids assuming that setting. Local processes do not perform
work while the machine is asleep.

When you return, reopen this Codex chat/project and start Docker Desktop if
needed. The checkpoint is in CURRENT_STATE.md and CONTINUATION_PROMPT.md. Say
"Resume from CURRENT_STATE and keep verified changes on GitHub." No
deck/Windows/worker approval needs repeating. Docker
storage is already relocated to D:\DockerData; check its available space before
a large image build.
