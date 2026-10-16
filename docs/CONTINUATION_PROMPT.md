# Continue RegIntel from the M1.12 administrator checkpoint

Continue sequential authorized work on existing main in
https://github.com/127yap101/RegIntel. Inspect Git/remote/environment and read
AGENTS.md, CURRENT_STATE.md, docs/M1_12_ADMIN_REVIEW_PLAN.md,
data/admin-review-validation-report.json and the newest PHASE_LOG entry first.
M1.12 and bounded M1/M1C implementation are complete. Source
4114407839a9a319fcf075a847c976a23dc2bfa9 is pushed normally to existing main.
Exact-source [run 38908935402](https://github.com/127yap101/RegIntel/actions/runs/38908935402) completed SUCCESS for
Windows foundation, Ubuntu foundation and Linux data infrastructure. Complete
foundation/database commands, fresh migrations 1–11 apply/replay, seeded-role
authentication and restart persistence pass. Public run/job/step conclusions are
verified; no raw-log per-test counts are inferred. All 27 source fingerprints
match; the final follow-up changes documentation/report metadata only. Proceed
sequentially to M2. Preserve teammate changes and inspect the actual Git log;
do not assume this local database exists on another machine.

M1.12 adds backend/src/regintel/admin and frontend/src/admin. New adapter GETs
are read-only/current-admin: /v1/admin/workspace/queues/{kind}, /reviews/{run_id}
and /metrics. They use bounded read-only transactions and verified frozen
candidate/source/gate data, retaining prior final reviews and accepted IDs.
Existing upload, processing, validation/review, exact administrator evidence/PDF
and publication APIs own all writes. No new mutation route or SQL migration.

Choose Administrator workspace in the frontend header. Its separate memory-only
session supports PDF upload, stored filing/workflow progress, explicit reviewed
metrics, dispatch/revalidation, quarantine and exact evidence, immutable
approval/rejection, reviewed publication drafts, exact amendment forms and
separate publish/rebuild actions. Mandatory gates cannot be overridden. Existing
accepted observations/final decisions cannot be edited or selected again.
Source dates/effects/parentage require explicit evidence; no latest-filing-wins.
Stable retry IDs and abort/private-state clearing are required behavior.

Local checks: 1932 backend passed/six native Windows skips in 495.16s; 489
database cases deselected. Thirty new API cases and six new disposable
PostgreSQL cases pass (13.41s). Final complete frontend passes lint/strict types/
build, 254 unit tests and 24 Chromium tests in 1.4m, including ten admin cases.
Ruff 199 files/mypy 131 sources, PowerShell/Bash syntax/actionlint/Node pass.
The combined native runner stopped at four test lint errors after backend
success; fixed test typing, then the complete frontend command passed. Do not
invent a successful combined native runner or full local 489-database result.
Earlier authored browser setup failures and fixes remain disclosed in the report.

Real read-only browser proof .cache/admin-browser-9daebf6d16ab4516bfb2e7550ee2feba passes parsed filing/
completed workflow navigation, sixteen checks, original immutable review and
acceptance, original PDF.js page 3/one persisted region, 375px, published manifest
scope and logout/no storage/credential URLs/browser errors. It attempts zero
authoritative writes. Source/processing/publication/authority snapshots are
unchanged. Three original stopped data containers were restored from unchanged
volumes; owned proof API/Vite processes are stopped. The preserved legacy
SOURCE_VERIFIED job is separate from the later PARSED job; do not delete it.

Read docs/07_BUILD_PHASES_FINAL.md and relevant M2 architecture/data/financial
contracts before proposing the next bounded implementation. M2 sequence is
company/profile, evidence viewer, normalization, formulas, comparison and
evaluation; no invented numbered subphases. M2 consumes published M1 facts and
owns POST /v1/compare and GET /v1/quotes. M1 owns company-search backend; M2 owns
profile experience. M4 owns immutable quote snapshots/ledger. Financial
compatibility, Decimal normalization/formulas and missing/conflicting/incompatible
inputs are deterministic backend responsibilities; models never calculate or
accept authoritative values. M3/M4/integration remain later.

Sequential implementation, meaningful tests, commits and normal pushes to
existing main are already authorized. Deck waiver, native Windows exception
and one private non-root Linux Celery/Docling worker approval persist; do not
repeat approvals. No force push/reset, destructive cleanup, system install,
unapproved infrastructure/architecture, public port or paid API/model call.
Use existing approved .env/.env.auth programmatically for localhost checks
without printing credentials. Never commit them, original PDFs/models,
Docker/database state, caches, screenshots or generated outputs.

PostgreSQL is authoritative; Neo4j/pgvector/BM25 derive from the same approved
published manifest. All eleven migrations and frozen parsing/entity/candidate/
validation/processing/publication/read/retrieval algorithms remain unchanged.
The 113-file protected-byte audit and 27 phase-source fingerprints are in the
measured report. Frozen 0011 SHA256:
310b96aec87ff153826cbc0a0edf997becb96a27e487e3624e3c18e2479ad9b6.
Processing configuration:
bacb112415f5728f813738f353f6c2765a9f0135177460e9497ab00e445b2dd6.
Worker image 5ea1bac10eb3ffdbfe7c3c060763b233f11f85a7096dec790f53243f46c1711b
retains its verified M1.8 parser/stage environments. No M1.9–M1.12 rebuild.
Docker data is D:/DockerData; preserve original volumes/accounts/assets.

Actual corpus: 614d7861-3f8f-4d5c-a9e5-d7423c2aba58;
manifest SHA 6622925d2516aedd4c04194372c7783983b00b14271a9d7edcb7ff5b65cda58e.
Company: 581d1b0d-98fd-4a23-8e15-5574dac650a2.
Observation: 4745db6c-09db-4ee2-bc43-efb8a53c7b6b.
Candidate: e30af8f7-a198-41e1-a039-a748ce516aef.
Fresh validation: 97ec299b-f5e7-4043-9fec-e7c08473b6a9.
Original final review: 5c42296e-e63f-4f84-9c52-ead243b9596c on older
f93660f2-c589-4cc5-af3d-031e896a4d3b.
Evidence: 7e340c65-8087-43cf-8d3c-2648b7c5f1b8, page_index2/span0..272.
Source SHA a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347.
Parse: 38819124-f764-4f41-acef-44ac000dbc45, 878 exact records.
Parsed filing job: c81a8c48-2895-4c00-8d88-e45a99bd114e.
Recovered workflow: 95ba9ce9-5f28-4187-a35b-3364415a838c.

Real data remains one conditional narrative, zero numerical/relation positives,
unresolved parent/effects0 and unknown publication date. No actual amendment
pair, gold/held-out effectiveness or provider model-selection outcome exists.
Authored tests are engineering evidence only. Existing OCR/table/currency
limitations, 64MB PDF/16-million-pixel bounds and the large JS bundle warning
remain. Live Gemini transport/model/budget, macOS/ARM and fresh real-source
clone reproduction are unverified.

Use Node24.19.0, project-local .tools/pnpm/pnpm.cmd11.19.0, Python3.12.14 and
the locked entities+publication extras. Both bootstraps generate separate shared/
read/retrieval/admin schema/types and authored fixtures; generated files stay
ignored. Native check runners install nothing. Keep ports8000/5173 free for
Playwright. Another machine must initialize its own ignored credentials and
acquire/restore its source PDFs/BGE assets/data; Git contains source and metadata.
Read docs/RUN_AND_CHECK.md for app launch, inspection and safe pause/resume.

Implement the authorized phase, verify meaningful behavior, review the diff,
update state/report/handoff, commit/push normally and inspect exact-source CI.
