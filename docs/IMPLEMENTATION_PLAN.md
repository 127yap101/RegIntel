# RegIntel Finance — Implementation and Verification Plan

Date: 2026-10-04. This execution plan supplements the unchanged final specifications. Acceptance checks below operationalize their milestones; they do not assert implementation or research results.

Update2026-10-06: M0.1–M0.6 are verified. The user explicitly waived the presentation
implementation gate and authorized M1A; the actual deck is still unverified. The
waiver supersedes the historical gate wording below. Current execution scope and
the pending supported Celery worker exception are in M1A_IMPLEMENTATION_PLAN.md.

## Scope and sequence

Windows development was explicitly approved by the user. The specified application stack is retained. M0 foundation work may proceed; deck verification is still required before M1/full application implementation. Complete and verify each phase before advancing. Project-local dependencies/setup are authorized; system installation, credentials, paid calls, public exposure, remote pushes and architecture changes retain the approval boundaries in `AGENTS.md`.

| Phase | Deliverables | Required verification before advancing |
|---|---|---|
| M0.1 | Local monorepo/Git, exclusions, preserved AGENTS/specs, current state and phase records | Git inventory/exclusions reviewed; final-document hashes unchanged; current state accurate |
| M0.2 | Python 3.12/uv and Node/pnpm project configuration; minimal FastAPI and React/strict-TypeScript/Vite foundations; test/lint/typecheck/build/CI configuration | Reproducible dependency sync; backend/frontend checks pass; CI mirrors local commands; versions recorded |
| M0.3 | PostgreSQL 16+pgvector, supported Neo4j and Redis in local Docker Compose; migration foundation | Compose configuration valid; services healthy; pgvector/connectivity verified; migrations apply on clean database and are repeatable |
| M0.4 | JWT application authentication and seeded admin/learner roles | Valid/invalid credentials, token validation and role separation tested; no committed secrets |
| M0.5 | API envelope, canonical IDs, enums, versions, evidence/geometry types, relation ontology and Decimal serialization | Naming/ownership conflicts explicitly resolved; Python/TypeScript contracts agree; Decimal strings round-trip safely |
| M0.6 | Synthetic PDF, contract and adversarial fixture generators/helpers | Reproducible fixture contents/expected outcomes; no false claims of extraction support or research performance |
| M1.1–1.4 | Ingestion schemas, admin upload/jobs, Docling/OCR provenance and authenticated evidence access | One controlled filing traverses durable ingestion to exact evidence; source geometry and recovery interfaces verified |
| M1.5–1.9 | Entity resolution, typed candidates, hard validation/review, recovery and amendment-aware atomic publication | Context/direction/adversarial checks; immutable history; explicit effects; idempotency; rebuildable projections |
| M1.10–1.12 | Published company/fact/graph APIs, B0–B3 retrieval/Q&A, admin/review UI | Version-consistent reads; support/citation checks; numeric routing; review/publication authorization |
| M2 | Profile/evidence viewer, normalization, formulas, comparison and evaluation | Compatible/missing/conflicting period/basis/unit cases and derived-input evidence tested |
| M3 | Reviewed glossary/definitions/examples, context and optional constrained paraphrase | Approved content and source/context fidelity; unchanged formula outputs |
| M4 | Quote snapshots, order validation, immutable ledger, cash/holdings and analytics | Fixed-price Decimal scenarios; duplicate/retry/concurrent requests; replay and atomic outcomes |
| I.1–I.4 | Real-filing slice, feature/corpus freeze, held-out evaluation, reproduction/handoff | End-to-end exact evidence display; frozen experiment records; fresh-clone setup and actual report assets |

M2–M4 subphase numbering is not defined individually in the supplied build file. Before those milestones, document a reviewed breakdown without inventing missing finalized requirements.

## Before M1

1. All M0 gates pass.
2. Verify the presentation corrections required by `09_FINALIZATION_AUDIT.md` §12 and `10_PPT_FINALIZATION_CHECKLIST.md`, or obtain an explicit user change to that gate.
3. Establish real filing manifests with source URLs/hashes and amendment metadata; do not invent or expand the seed corpus.
4. Configure/benchmark a supported OCR fallback only when parsing requires it.
5. Authorize a model-call budget and credential access before paid provider usage. Model selection remains benchmark-dependent; no model alias is preselected here.

## Approved contract decisions — implement in M0.5

- User explicitly approved these three resolutions on 2026-10-04; finalized specs remain unchanged.
- Supersession: use `SUPERSEDE` as the canonical enum following the detailed research taxonomy, documenting architecture's `SUPERSEDES` wording rather than silently accepting two stored values.
- Search: M1 owns published-company lookup/search APIs; M2 owns consuming search/profile UI.
- Quotes: preserve M2 ownership of `GET /v1/quotes`; M4 stores immutable quote references/version, Decimal price, currency and timestamp for orders.
- API envelope, ID format and JWT settings require recorded implementation choices during their phases; they are not fixed by the approved conflict resolutions above.

## Track record and safe continuation

Each `PHASE_LOG.md` entry records phase name/status, tasks, files, commands/results, decisions, problems/fixes and remaining work. Update `CURRENT_STATE.md` after each completed phase and before stopping. Near the context limit, produce `docs/CONTINUATION_PROMPT.md` with the goal, stack, approvals/constraints, verified phases, active work, files, commands, decisions, failures/fixes, results and exact next action. No work is complete merely because code/configuration exists.
