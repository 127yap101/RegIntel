# RegIntel Finance — Final Technology, Data and Deployment Specification

## 1. Technology stack

| Layer | Final pilot decision |
|---|---|
| Development OS | macOS Apple Silicon |
| Editor/execution | VS Code + GPT-6 Astra/Codex |
| Backend | Python 3.12, FastAPI, Pydantic v2 |
| DB | PostgreSQL 16, pinned tested patch |
| Vector | pgvector |
| Lexical | BM25 baseline |
| Graph | Neo4j, pinned tested supported release |
| Jobs | Celery + Redis |
| PDF parsing | Docling |
| OCR | one explicitly configured, benchmarked supported OCR engine |
| Entity rules | spaCy EntityRuler |
| Fuzzy matching | RapidFuzz |
| Embeddings | BAAI/bge-small-en-v1.5 baseline |
| LLM | hosted Gemini through provider adapter; model selected by benchmark |
| Frontend | React + TypeScript + Vite |
| UI | Tailwind CSS + reusable component kit |
| Graph UI | Cytoscape.js |
| PDF evidence viewer | PDF.js |
| Charts | ECharts |
| Tests | pytest + Vitest/Testing Library + Playwright |
| CI | GitHub Actions |
| Local infrastructure | Docker Compose |

## 2. What is deliberately not preselected

Do not lock a Gemini model only because it sounds stronger.

Benchmark accessible current models on the same tuning set covering:

- relations;
- financial tables;
- missing metadata;
- OCR noise;
- unsupported questions.

Record:

- source correctness;
- period/basis/unit correctness;
- unsupported proposal rate;
- abstention behavior;
- p50/p95 latency;
- cost.

Then freeze:

- model ID;
- SDK version;
- generation settings;
- prompt hash;
- schema hash.

A project paper must report the actual configuration used.

## 3. Embedding baseline

Use:

`BAAI/bge-small-en-v1.5`

Known baseline characteristics:

- 384 dimensions;
- 512-token sequence limit.

Start with approximately 350–450 embedding-token chunks, measured with the model tokenizer and including titles/table headers/query prefix/special tokens.

Never silently truncate.

## 4. Financial arithmetic

Authoritative business values use:

- Python `Decimal`;
- PostgreSQL `NUMERIC`;
- decimal strings in JSON.

Floating point is permitted for:

- embeddings;
- similarity scores;
- coordinates;
- latency;
- chart/display calculations.

It must not feed authoritative financial arithmetic.

## 5. Filing corpus

Current project seed:

- Waaree Energies;
- Premier Energies;
- Vikram Solar;
- SAEL Industries.

Prefer:

- RHP;
- DRHP;
- prospectus;
- addendum;
- corrigendum.

The capstone corpus currently lists approximately eight source documents. The target is about ten. Add two only after the vertical slice is reliable.

Do not commit original PDFs to Git.

Use a manifest:

```json
{
  "filing_id": "...",
  "company_id": "...",
  "source_url": "...",
  "sha256": "...",
  "document_type": "rhp",
  "published_at": "...",
  "parent_filing_id": null
}
```

## 6. Amendment metadata

Minimum lineage fields:

- parent filing ID;
- child filing ID;
- lineage type;
- publication date;
- affected section/reference;
- effect type where established;
- evidence IDs;
- reviewer/decision when semantic judgment is required.

## 7. Data-state model

```text
raw filing
    |
    v
parsed artifact
    |
    v
candidate
    |
    +--> review
    |
    +--> quarantine
    |
    v
accepted observation
    |
    v
building corpus
    |
    v
published corpus
    |
    +--> active/as-of projection
    +--> historical projection
```

## 8. Local deployment

Infrastructure:

```text
docker compose up
├── postgres + pgvector
├── neo4j
└── redis
```

Application:

```text
uv run <FastAPI/Celery commands>
pnpm <frontend commands>
```

Exact package/container versions are established by Astra in Phase 0 and recorded in `docs/dependency_versions.md`.

## 9. Dependency policy

A dependency is added only when:

1. required by the current milestone;
2. officially documented;
3. license-compatible;
4. non-duplicative;
5. exact version is recorded.

Do not install the complete future stack on day one.

## 10. Repository policy

Keep:

```text
AGENTS.md
CURRENT_STATE.md
PROJECT_CHARTER_FINAL.md
SYSTEM_ARCHITECTURE_FINAL.md
M1_RESEARCH_METHOD_FINAL.md
TECH_STACK_AND_DATA_FINAL.md
EVALUATION_PLAN_FINAL.md
ASTRA_RUNBOOK_FINAL.md
BUILD_PHASES_FINAL.md
RUNTIME_MODEL_CONTRACT_FINAL.md
```

and implementation directories:

```text
backend/
frontend/
contracts/
data/
docs/
eval/
scripts/
```
