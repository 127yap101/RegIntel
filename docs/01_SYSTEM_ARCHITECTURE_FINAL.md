# RegIntel Finance — Final System Architecture

## 1. Architecture principle

Use a modular monorepo with one authoritative backend and rebuildable projections.

```text
                         PUBLIC SEBI FILINGS
                    DRHP / RHP / ADDENDUM / CORRIGENDUM
                                |
                                v
                     [1] INGESTION + LINEAGE
                  file hash / filing metadata / version
                                |
                                v
                    [2] DOCUMENT UNDERSTANDING
              PDF -> pages -> blocks -> tables -> cells
                    Docling + targeted OCR fallback
                                |
                                v
                     [3] ENTITY + CANDIDATE LAYER
                   entity detection + canonical IDs
                                |
                    +-----------+-----------+
                    |                       |
                    v                       v
              candidate facts        candidate relations
              numeric/narrative       typed relations
                    |                       |
                    +-----------+-----------+
                                |
                                v
                  [4] EVIDENCE / CONTEXT GATE
          source + entity + relation + value + period/unit/basis
                                |
                     +----------+----------+
                     |                     |
                   PASS              REVIEW / QUARANTINE
                     |                     |
                     v                     |
             accepted observation <--------+
                     |
                     v
              [5] AMENDMENT RESOLUTION
       link parent/child filings and explicit fact effects
                     |
                     v
             [6] VERSIONED CORPUS BUILD
            historical observations + active view
                     |
             +-------+---------------+
             |                       |
             v                       v
       PostgreSQL authority       Neo4j projection
       + pgvector/BM25             for graph traversal
             |                       |
             +-----------+-----------+
                         |
                         v
                [7] RETRIEVAL / ANALYSIS
             dense + BM25 + RRF + graph
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
         M1             M2             M3
      corporate       compare        learning
      intelligence
          |
          +----------------------+
                                 |
                                 v
                                M4
                         virtual portfolio
                                 |
                                 v
                           WEB DASHBOARD
```

## 2. Data ownership

### PostgreSQL — authoritative source

Stores:

- users/roles;
- filings;
- immutable source metadata;
- parsing artifacts;
- pages/blocks/tables/cells;
- evidence;
- entities/aliases;
- candidates;
- accepted facts;
- accepted relations;
- amendment lineage;
- effect decisions;
- review/audit;
- corpus versions;
- retrieval chunks/embeddings;
- M3 glossary;
- M4 ledger.

### Neo4j — published graph projection

Neo4j contains only publication-approved graph observations.

Example:

```text
(:Company)-[:OWNS]->(:Company)
(:Company)-[:PROMOTER_OF]->(:Company)
(:Company)-[:SUBSIDIARY_OF]->(:Company)
(:Company)-[:SUPPLIES_TO]->(:Company)
(:Company)-[:AUDITS]->(:Company)
(:Company)-[:LENDS_TO]->(:Company)
```

Every graph edge retains:

- observation/relation ID;
- corpus version;
- observed/source date;
- effective date only when explicitly stated;
- ownership stake/denominator where applicable;
- evidence IDs;
- accepted status;
- amendment lineage/effect metadata where applicable.

Neo4j is rebuildable from the published PostgreSQL corpus.

### pgvector/BM25 retrieval projection

Retrieval data is tied to the same corpus version.

Use structure-aware chunks containing:

- title/section context;
- repeated table headers;
- page/evidence IDs;
- company context;
- period/basis metadata.

## 3. Amendment-aware version model

A filing is not assumed to be a complete replacement for every previous filing.

Represent:

```text
Filing A
   |
   +-- ADDENDUM_TO / CORRIGENDUM_TO --> Filing B
                                        |
                                        v
                              affected evidence/facts
                                        |
                       +----------------+----------------+
                       |                |                |
                      ADD           CORRECT         SUPERSEDES
```

Only create an effect such as `SUPERSEDES` when the source or a reviewed decision establishes it.

Do not automatically mark an earlier fact stale simply because a later document exists.

Maintain two views:

### Historical view

All accepted observations remain queryable.

### Active/as-of view

For a requested corpus version or filing date, expose the observation set that is valid under the recorded amendment/effect rules.

This prevents “latest row wins” logic from hiding historical contradictions.

## 4. M1 module boundary

M1 owns:

- filing ingestion;
- document parsing;
- evidence;
- entity resolution;
- extraction candidates;
- validation;
- review/quarantine;
- amendment lineage/effect handling;
- publication;
- Neo4j projection;
- retrieval support.

M2, M3 and M4 consume published data through stable contracts. They do not modify M1 facts directly.

## 5. M2 boundary

M2 owns:

- company search/profile;
- comparison;
- metric compatibility;
- unit normalization;
- period/basis alignment;
- derived formulas;
- missing/incompatible warnings;
- evidence-viewer integration.

M2 consumes M1 company graph/fact APIs.

## 6. M3 boundary

M3 owns:

- reviewed glossary;
- definitions;
- examples;
- source-linked explanations;
- optional constrained paraphrase.

M3 does not create authoritative filing facts.

## 7. M4 boundary

M4 owns:

- virtual accounts;
- quotes/snapshots;
- orders;
- ledger;
- holdings/cash;
- analytics;
- post-commit explanatory feedback.

M4 has no real execution.

## 8. Retrieval architecture

Four controlled arms:

### B0 — Dense baseline

BGE-small-en-v1.5 on structure-aware chunks.

### B1 — Filtered dense

B0 + reliable company/period/basis filters.

### B2 — Hybrid

B1 + BM25 + Reciprocal Rank Fusion + table-aware chunks.

### B3 — Graph-assisted

B2 + bounded 1–2 hop Neo4j expansion + re-application of all filters.

Initial RRF:

```text
RRF(d) = Σ 1 / (60 + rank_i(d))
```

Keep top candidates within a fixed context budget.

## 9. Evidence geometry

Store:

- zero-based page index;
- PDF.js page = page_index + 1;
- unrotated PDF-point coordinates;
- bottom-left origin;
- page dimensions;
- crop box;
- rotation;
- table/cell/header references.

Cross-page support uses multiple evidence records.

## 10. Security trust boundary

Filing text is untrusted data.

The runtime model receives:

- fixed instructions;
- serialized source data.

The model does not get tools that can:

- browse;
- write to databases;
- publish facts;
- change user permissions;
- place portfolio trades.

Application code controls:

- IDs;
- arithmetic;
- authorization;
- evidence membership;
- acceptance;
- publication;
- versioning;
- accounting.

## 11. Local development

```text
VS Code
 |
 +-- React/TypeScript frontend
 |
 +-- FastAPI/Celery backend
 |
 +-- Docker Compose
       +-- PostgreSQL + pgvector
       +-- Neo4j
       +-- Redis
```

Run application code natively on macOS. Use containers for infrastructure services. Do not expose database ports publicly.

## 12. Architecture restraint

Do not introduce:

- Milvus;
- Qdrant;
- FAISS as a second retrieval store;
- Elasticsearch;
- Kubernetes;
- general multi-agent frameworks;
- fine-tuning infrastructure;

unless an experiment demonstrates a concrete pilot requirement that cannot otherwise be met.
