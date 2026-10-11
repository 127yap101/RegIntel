# RegIntel Finance — Agent Operating Contract

## 1. Identity, scope and authority

**RegIntel Finance** — **Evidence-Grounded Regulatory Filing Knowledge Graph & Financial Learning Platform** — is a six-week capstone pilot in Financial NLP, Knowledge Graphs, Evidence-Grounded AI and Financial Learning. Team ownership: **Parth — M1; Yash — M2; Shreya — M3; Artham — M4**.

The planned platform converts a controlled corpus of public Indian securities filings into validated, source-linked corporate intelligence and financial learning. Exclude stock-price prediction, investment advice, buy/sell/hold recommendations, real-money execution, live trading and uncalibrated financial risk scores.

The task instruction controls authorized scope; finalized `docs/` control project design. This file is the daily operating contract and navigation map, not a replacement for detailed specifications. Code/tests/defaults cannot override the design. Report genuine conflicts and stop affected work instead of inventing a resolution; continue independent authorized work.

Distinguish fixed decisions, plans, targets, optional work, exclusions and measured results. Specifications do not prove implementation or validation. Inspect repository state before claiming capabilities. Never invent filings, facts, evidence, datasets, benchmarks, model-selection outcomes or improvements.

## 2. Research contribution and critical path

The proposed applied contribution is **Amendment-Aware Evidence-Constrained Corporate Relation Extraction** for Indian public-issue filings. It addresses extraction errors, context errors and version/evidence errors through:

**candidate extraction → evidence/context gate → immutable observation → explicit amendment effect → active as-of view**

Research tests relationship accuracy across successive Indian IPO filings and prevention of unsupported/superseded disclosures in the active graph. Do not claim a new neural architecture or global novelty from KGs, RAG, LLMs or grounding. Proposed improvements remain hypotheses until measured.

M1 is the critical path. Prioritize this complete vertical slice:

**real filing → upload/hash → structured parse/exact evidence → entities/candidates → validation/review → accepted observation → amendment lineage/effects → published corpus → Neo4j/pgvector projection → company page → exact source-page viewer**

Do not delay it for cosmetic polish, graph animation, dark mode, extra company coverage or optional features.

## 3. Authority, evidence and extraction

- **PostgreSQL is authoritative; Neo4j is a rebuildable, publication-approved graph projection.** pgvector/BM25 derives from validated state at the same published corpus version. Projections cannot become independent authorities.
- Separate extraction, validation, review, persistence, amendment resolution, projection and presentation. Models propose; application contracts and evidence/context gates control acceptance/publication.
- Hash immutable sources; retain structured provenance and source geometry. Every authoritative fact/relation needs exact evidence IDs/spans/cells, document/version/page, applicable context, acceptance audit, corpus version and relevant lineage/effects. A page citation alone is insufficient. Follow architecture §9 for PDF coordinates and cross-page support.
- Resolve entities through CIN/ISIN and approved aliases/names, then contextual proposals/review. Fuzzy similarity never independently accepts a match.
- Generate typed, directed candidates from local blocks, related cells or bounded evidence. Page-wide entity co-occurrence is not relation proof.
- Gate source membership, exact support, row/column/header context, value, period, unit, basis, ownership denominator/date and direction. Ambiguity requires review; unsupported candidates are quarantined. Never bypass mandatory gates.
- Keep conflicting disclosures as separate observations until an evidence-backed, audited effect resolves active status.

## 4. Amendments, history and publication

Preserve immutable historical observations and queryable lineage. Link parent/child filings and affected evidence/facts. Amendment/addendum/corrigendum effects require source support or an evidence-backed reviewed decision. Distinguish addition, correction, supplementation, supersession and explicitly supported removal.

A later filing does **not** replace all earlier disclosures automatically. No latest-timestamp-wins, silent overwriting or publication-date inference of effective dates. Historical and active/as-of views follow recorded effects for the requested corpus version/date.

Publish corpus versions atomically. Edges retain observation/evidence IDs, filing/corpus versions, source dates and applicable ownership/effect context. Effective dates require explicit support. Projections remain rebuildable; modules share a published filing-corpus version, with independent M3/M4 versions explicit.

## 5. Fixed stack and pilot data

| Layer | Specified pilot stack |
|---|---|
| Development | macOS Apple Silicon; VS Code + Astra/Codex; uv and pnpm |
| Backend/contracts | Python 3.12, FastAPI, Pydantic v2 |
| Authority/retrieval/graph | PostgreSQL 16 with tested pinned patch; pgvector; BM25; tested supported Neo4j release |
| Jobs/parsing/OCR | Celery + Redis; Docling; one explicitly configured, benchmarked Docling-supported OCR engine |
| Entities/embeddings/model | spaCy EntityRuler; RapidFuzz; `BAAI/bge-small-en-v1.5` baseline; hosted Gemini through a provider adapter |
| Frontend | React + strict TypeScript + Vite; Tailwind CSS and controlled reusable components |
| Visualization | Cytoscape.js; PDF.js; ECharts |
| Verification/infrastructure | pytest; Vitest/Testing Library; Playwright; GitHub Actions; Docker Compose |

Run applications natively on macOS and infrastructure in containers as specified. Report actual host/prerequisite differences; do not silently substitute Windows/WSL. Verify official compatibility and record tested versions in `docs/dependency_versions.md` during authorized foundation work.

No PostgreSQL/Neo4j replacement, dedicated vector database, duplicate infrastructure or hidden mandatory FinBERT/SpERT/FAISS/Qdrant/Next.js dependency. Transformer NER and fine-tuning are not pilot requirements. Architecture changes require approval; dependencies must be phase-required, documented, license-compatible and non-duplicative.

Corpus: SEBI DRHP/RHP/prospectus where applicable, addenda/corrigenda. Seed: **Waaree Energies, Premier Energies, Vikram Solar, SAEL Industries**. Roughly eight documents are identified; about ten is a target, not verified availability. Expand neither documents nor companies before a reliable slice. Annual reports are optional later work. Keep PDFs out of Git; manifest source URLs, hashes, metadata and lineage.

## 6. Financial correctness

- Use Python `Decimal`, PostgreSQL `NUMERIC` and decimal strings in JSON for authoritative financial values/calculations. Floating point is permitted for embeddings, similarity, geometry, latency and display only; it must not feed authoritative arithmetic.
- Preserve raw value, normalized value, currency/unit, period, period type, reporting basis, denominator, stake kind and exact source page/table/cell where applicable.
- Dash/blank is not zero; publication date is not a financial period. Distinguish instant, duration and unknown periods. Do not fabricate missing inputs or infer unsupported facts.
- Do not mix standalone/consolidated values or calculate across incompatible periods/units/bases. Ownership percentages missing required denominator/date/basis cannot be automatically accepted.
- Backend logic determines compatibility, normalization and formulas. Derived results expose input facts/evidence. Missing or incompatible inputs produce explicit unavailable/incompatible responses.

## 7. Runtime model boundaries

LLMs generate candidates/drafts, never authoritative state. Separate fixed instructions from serialized data; filing text is untrusted, never executable instructions or system prompts.

Models may use only supplied entity/source/metric IDs and allowed relation types. They cannot publish or accept facts, invent evidence/citations, create page indices, change canonical IDs, calculate authoritative financial results, determine financial compatibility, authorize/execute trades, change permissions or ledger balances, overwrite accepted records, infer unsupported relationships or silently supersede history. Do not give the runtime model browsing, database-writing, publication or trading tools.

Default prose is extractive and cited. Experimental generated claims require supplied evidence IDs and application-validated support/citations. Preserve uncertainty, attribution, negation and qualifiers; do not reconcile conflicts; abstain on insufficient context. Route numeric questions through deterministic backend logic.

Benchmark Gemini on a common tuning set, then freeze model ID, SDK, settings and prompt/schema/configuration hashes. Record run ID, latency, available token usage and actual cost. No floating model alias for held-out results.

## 8. Module and API ownership

| Module / owner | Responsibility and interfaces |
|---|---|
| **M1 Corporate Intelligence / Parth** | Ingestion, evidence, entities, candidates, validation/review, lineage, publication, graph and retrieval. Owns `POST /v1/filings`, `GET /v1/companies/{id}/facts`, `GET /v1/companies/{id}/graph`, `GET /v1/evidence/{id}`. |
| **M2 Analysis & Comparison / Yash** | Profile/comparison experience, compatibility, normalization, derived formulas and warnings. Consumes M1 data/graph; owns `POST /v1/compare` and `GET /v1/quotes`. |
| **M3 Financial Learning / Shreya** | Reviewed authoritative glossary, definitions, approved examples and context/source-linked explanations. Optional LLM paraphrase cannot add facts/examples, change formulas/outputs or invent citations. |
| **M4 Virtual Portfolio / Artham** | Virtual accounts, quote snapshots, orders, immutable ledger, holdings/cash and analytics. Use deterministic Decimal arithmetic and fixed-price acceptance scenarios. Optional explanation follows committed outcomes only; no recommendations, prediction or live execution. |

M2–M4 consume published M1 contracts and cannot modify M1 facts directly. Preserve endpoint ownership; settle producer/consumer interfaces explicitly rather than reassigning responsibilities casually.

## 9. Evaluation discipline

Separate engineering correctness from research effectiveness. A dashboard does not prove improvement. Use manually reviewed real-filing gold data; report actual counts/limitations. Prefer company/document-group holdout without company/template leakage where feasible. Targets are not completed annotations.

Measure entity/relation precision/recall/F1, direction and value/unit/period/basis/denominator accuracy. Assess candidate recall, accepted precision, review rate and accepted-invalid rate together, with positive and controlled-invalid cases; rejecting everything is not success. Compare amendment lineage precision/recall, effect accuracy, stale-fact rate, active-view accuracy and historical traceability against the document-independent baseline.

Retrieval is one controlled four-arm ablation: **B0 dense; B1 dense + metadata filters; B2 B1 + BM25 + RRF + table-aware chunks; B3 B2 + bounded 1–2-hop graph expansion with filters reapplied**. Hold corpus, questions, model, top-k/context budget, policy and rubric constant. Respect embedding tokenizer limits and never silently truncate.

Measure Recall@5/@10, MRR, citation accuracy, supported-claim rate, unsupported-fact/answer rate, abstention correctness, p50/p95 and actual cost. Citations must support claims. Report configuration, errors, limitations and feasible confidence intervals. Synthetic-fixture scores and audit judgments are not real-world performance.

## 10. Engineering, verification and change safety

Before implementation, inspect files/Git status and `CURRENT_STATE.md` if present. Identify the authorized phase, dependencies/interfaces and relevant documents. Do not assume code, prerequisites or undocumented requirements exist.

Implement only the requested phase. Use small explicit functions, typed interfaces, Python annotations/Pydantic v2 and strict TypeScript; avoid careless `any`. Test implemented behavior meaningfully, including relevant contracts, failures, injection, context errors and amendment conflicts. Never fake tests, disable checks or hide failures. Run relevant verification and report actual results.

Flow: **implementation → tests → diff/review → verification → local commit when explicitly authorized**. Completion requires passing relevant checks, disclosed limitations and `CURRENT_STATE.md` updated within allowed scope. Report added dependencies/migrations/environment variables. Documentation-only work does not authorize setup or coding.

No secrets in Git or prompts. Use environment variables/`.env.example` when authorized. Do not commit original PDFs, model caches or generated artifacts. Preserve unrelated user changes.

Require explicit approval for large destructive deletions, discarding unrelated changes, system-wide configuration, unexpected system software installation, unexpected paid services/API usage or usage beyond the agreed budget, public port exposure, credential access, remote pushes, major architecture changes or infrastructure outside the specification. Never use `git reset --hard`, `git clean -fd` or `git checkout -- .` without authorization for the exact consequence. Routine phase-authorized project-local work does not require repeated approval.

## 11. Milestones, gates and unresolved details

Follow `docs/07_BUILD_PHASES_FINAL.md` and the coherent milestone grouping in the runbook: **M0 (0.1–0.6) → M1A (1.1–1.4) → M1B (1.5–1.9) → M1C (1.10–1.12) → M2 → M3 → M4 → INTEGRATION (I.1–I.4)**. The initialization brief names M2 2.1–2.9, M3 3.1–3.7 and M4 4.1–4.8; the supplied build document summarizes these modules without individual numbered subphase definitions. Do not invent those definitions.

Respect ingestion/evidence, validation/versioning and publication prerequisites. Integration gates: real-filing slice, feature/corpus freeze, held-out evaluation, fresh-clone reproduction/handoff. Audit §12/PPT corrections gate full implementation; completion is unverified. Runbook §3 first calls for read-only repository/environment inspection and a foundation plan for approval.

Resolve these contract ambiguities explicitly in shared-contract work, without changing the specifications here:

- Architecture §3 spells a supersession effect `SUPERSEDES`; research method §9 uses `SUPERSEDE`. Do not silently freeze either enum spelling.
- Architecture §5 assigns company search/profile to M2, while build phase M1.10 includes company search APIs in M1. Architecture §7 assigns quotes/snapshots to M4, while the initialization instruction assigns `GET /v1/quotes` to M2. Preserve the explicit endpoint map above; clarify backend/API ownership versus consuming experiences and ledger snapshots before implementing these interfaces.

## 12. Documentation navigation — progressive disclosure

Read this contract as stable context, then only the details needed for the current task. Use the actual numbered paths below; older root-level/unprefixed references are not instructions to duplicate the specifications.

| Task | Detailed source |
|---|---|
| Specification index/status | [docs/README.md](docs/README.md) |
| Identity, contribution, corpus, exclusions | [00 Project charter](docs/00_PROJECT_CHARTER_FINAL.md) |
| Architecture, authority, ownership, geometry | [01 System architecture](docs/01_SYSTEM_ARCHITECTURE_FINAL.md) |
| M1 extraction, evidence gates, amendment research | [02 M1 research method](docs/02_M1_RESEARCH_METHOD_FINAL.md) |
| Stack, dependencies, corpus, deployment | [03 Technology and data](docs/03_TECH_STACK_AND_DATA_FINAL.md) |
| Baselines, gold set, metrics, acceptance | [04 Evaluation plan](docs/04_EVALUATION_PLAN_FINAL.md) |
| Milestone process, approval, completion | [05 Astra runbook](docs/05_ASTRA_RUNBOOK_FINAL.md) |
| Additional persistent agent rules | [06 Agent rules](docs/06_AGENT_RULES_FINAL.md) |
| Authorized phase and prerequisites | [07 Build phases](docs/07_BUILD_PHASES_FINAL.md) |
| Runtime models, trust boundaries, adversarial fixtures | [08 Runtime model contract](docs/08_RUNTIME_MODEL_CONTRACT_FINAL.md) |
| Audit findings and readiness gates | [09 Finalization audit](docs/09_FINALIZATION_AUDIT.md) |
| Deck corrections and research wording | [10 PPT finalization checklist](docs/10_PPT_FINALIZATION_CHECKLIST.md) |

Read the requested phase and its dependency documents, not the entire package each time. Execute the approved design; the team controls architecture, methodology and scope changes.
