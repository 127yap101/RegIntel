# RegIntel Finance — Final Build Milestones

## M0 Foundation

### M0.1 Repository + instructions
Create monorepo, docs, AGENTS.md, `.gitignore`, `CURRENT_STATE.md`.

### M0.2 Toolchain + CI
Python/uv, Node/pnpm, React/Vite, FastAPI, tests, lint/typecheck, CI.

### M0.3 Data infrastructure
PostgreSQL + pgvector, Neo4j, Redis, Docker Compose, migrations.

### M0.4 Auth
JWT-based application authentication, seeded admin/learner roles.

### M0.5 Shared contracts
API envelope, IDs, enums, version identifiers, evidence types, relation ontology, Decimal serialization.

### M0.6 Fixtures
Synthetic PDF fixtures, contract fixtures, adversarial fixtures, test helpers.

## M1A Ingestion + Evidence

### M1.1 Ingestion models
Filing, parse, page, table/cell, evidence, candidate, fact, relation, version schemas.

### M1.2 Upload/jobs
Admin upload, hashing, deduplication, durable job dispatch.

### M1.3 Parsing
Docling adapter, page/table/cell provenance, OCR fallback, normalized coordinates.

### M1.4 Evidence
Evidence persistence and authenticated PDF/range access.

## M1B Extraction + Validation + Versioning

### M1.5 Entity resolution
CIN/ISIN, aliases, EntityRuler, RapidFuzz proposal/review.

### M1.6 Candidate extraction
Schema-constrained relation/numeric/narrative candidates with source IDs.

### M1.7 Validation/review
Hard context/evidence gate, quarantine, reviewer decisions.

### M1.8 Recovery/idempotency
Checkpointed worker stages, duplicate protection, failure recovery.

### M1.9 Amendment-aware publication
Lineage, explicit effects, historical observations, active/as-of view, Neo4j and retrieval projections, atomic corpus publication.

## M1C APIs + Retrieval

### M1.10 Company/fact/graph APIs
Published corpus reads, company search, facts and graph.

### M1.11 Retrieval/Q&A
B0–B3, RRF, bounded graph expansion, citation/support checks, numeric routing.

### M1.12 Admin/review UI
Filing jobs, quarantine, review, approval/correction, publication.

## M2 Comparison

Company/profile → evidence viewer → metric normalization → formulas → comparison → evaluation.

## M3 Financial Learning

Glossary → definitions → examples → context → optional constrained paraphrase → evaluation.

## M4 Virtual Portfolio

Ledger → quotes → order validation → transaction atomicity → holdings/cash → analytics → evaluation.

## Integration

### I.1 Vertical slice
One real filing from upload to exact evidence-backed graph/company view.

### I.2 Feature freeze
All modules consume the same published filing corpus version; independent M3/M4 versions remain explicit.

### I.3 Held-out evaluation
Run frozen experiments and error analysis.

### I.4 Reproduction/handoff
Fresh clone/setup, tests, demo script, documentation, report/paper assets.
