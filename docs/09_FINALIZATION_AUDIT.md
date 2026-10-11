# RegIntel Finance — Deep Finalization Audit

## Executive verdict

The project is **conceptually strong but was not internally final yet**.

The new final specification corrects the main consistency and research-defensibility issues found by reviewing:

- the six v2 project documents;
- the 36-page Capstone Midsem PDF;
- the older implementation/runtime prompt specifications;
- current external technical/model documentation;
- current overlapping financial-KG/GraphRAG work.

### Assessment

| Dimension | Before correction | Final target |
|---|---:|---:|
| Product concept | 8.5/10 | 9/10 |
| Engineering architecture | 8.5/10 | 9/10 |
| Internal consistency | 6.5/10 | 9/10 |
| Research defensibility | 6/10 | 8.5/10 |
| Six-week feasibility | 7/10 | 8.5/10 |
| Astra readiness | 7/10 | 9.5/10 |

These are professional judgment scores, not benchmark measurements.

## 1. What was already strong

### Evidence-first architecture

The project correctly makes source evidence, context and acceptance first-class rather than treating citations as decoration. The project charter requires every authoritative fact/relation to resolve to document/version, page, evidence and context. fileciteturn25file0L131-L145

### Separation of authority from generation

The architecture correctly makes PostgreSQL authoritative and Neo4j a rebuildable projection. fileciteturn25file1L5-L18

### Safe model boundary

The M1 method correctly says the LLM proposes candidates and does not decide acceptance. fileciteturn25file2L117-L148

### Research evaluation exists

The evaluation plan separates engineering correctness from research effectiveness and defines controlled baselines. fileciteturn25file4L5-L18

### Adversarial thinking

The method explicitly tests wrong units, wrong periods, missing ownership context, wrong relation direction, OCR corruption and unsupported claims. fileciteturn25file2L376-L397

## 2. Critical inconsistency found in the midsem deck

The PDF's technical architecture slide does not match the later technology/method slides.

The deck's architecture section shows a processing stack containing **FinBERT + SpERT** and a retrieval/storage layer containing **FAISS/Qdrant**, and it labels the frontend as **React/Next.js**. However, the deck's later software-requirements slide lists **spaCy EntityRuler + RapidFuzz, BGE-small-en-v1.5 + pgvector + BM25, Gemini API + Pydantic, PostgreSQL + Neo4j, and Docker/Git**, and the M1 algorithm slide separately describes Docling, spaCy, RapidFuzz and schema-constrained LLM extraction.

This is a genuine finalization blocker: a reviewer can see two different architectures in the same deck.

### Required correction

The final deck must use one stack:

```text
Docling + OCR
spaCy EntityRuler + RapidFuzz
schema-constrained Gemini candidate extraction
PostgreSQL + pgvector + BM25
Neo4j
FastAPI
React + TypeScript + Vite
Cytoscape.js
PDF.js
Docker Compose
```

Do not present FinBERT+SpERT as a core implemented algorithm unless the team actually builds, trains/evaluates and documents it.

The deck's M1 extraction slide is already much closer to the final method. fileciteturn28file1

## 3. Retrieval-arm correction

The final architecture must say **four** retrieval arms, not three.

They are B0, B1, B2 and B3. The current v2 architecture accidentally calls them three arms while listing four. fileciteturn25file1L204-L240

The revised document fixes this.

## 4. API ownership correction

The midsem ownership slide assigns graph retrieval to M2, while the implementation architecture assigns the corporate graph and retrieval support to M1.

Final rule:

**M1 implements the corporate graph/fact APIs. M2 consumes them.**

M2's responsibility is comparison/analysis, not ownership-graph extraction.

## 5. Corpus correction

The capstone deck currently identifies a small corpus built from Waaree Energies, Premier Energies, Vikram Solar and SAEL Industries filings. fileciteturn28file2

The final specification therefore narrows the primary corpus to:

**DRHP / RHP / prospectus / addenda / corrigenda**

and treats “about 10 filings” as a target rather than pretending the currently listed documents already total ten.

This is also an opportunity: the amendment documents are not noise. They are useful for the project's version-awareness research question.

## 6. The biggest research problem: novelty

The original “ECRE” description is useful engineering, but **ECRE alone should not be presented as a globally novel algorithm**.

Current external literature already contains combinations of:

- financial knowledge graphs;
- document parsing;
- GraphRAG;
- corporate relationships;
- source-grounded retrieval;
- regulatory/financial information extraction.

For example, current GraphRAG/capital-markets work already uses SEC filings, entity/relationship graphs, vector retrieval and exact text chunks, while recent financial KG work explores entity resolution, temporal modeling and disclosure relationships.

Therefore the safe academic statement is:

> “We propose and evaluate an amendment-aware evidence-constrained extraction and publication protocol for Indian IPO filings.”

Do not say:

> “No existing system does this.”

The midsem deck already wisely says its research gap is about the selected paper set and integration scope, not a claim that these features are absent everywhere. This wording should be preserved.

## 7. Why amendment-awareness is the better upgrade

The actual corpus contains addenda/corrigenda/RHPs. That means the project can investigate a concrete problem that ordinary independent-document extraction does not solve:

```text
Earlier disclosure
      |
      v
Later amendment
      |
      +--> add / correct / supplement / supersede
      |
      v
Active as-of view
```

This is stronger than simply adding another RAG component.

Research metrics can directly test:

- lineage accuracy;
- effect classification accuracy;
- stale-fact rate;
- active-view correctness;
- historical traceability.

The contribution becomes tied to the actual data rather than to architecture buzzwords.

## 8. Model-selection correction

The older runtime/build documents include historic Gemini/stack details and a WSL2/Linux baseline.

Those should not be treated as current project facts.

The current model must be benchmark-selected. The current Google documentation should be rechecked at installation, and the final evaluation should freeze the exact model ID/configuration.

Likewise, do not require a FinBERT/SpERT training pipeline unless the actual labeled set and schedule justify it.

## 9. Astra-context correction

The old runbook was too rigid:

- reading many documents before almost every task;
- one tiny phase per session;
- requiring repeated architecture rediscovery.

That is not optimal for a strong long-context coding model.

The final runbook uses:

```text
stable AGENTS.md
+
small CURRENT_STATE.md
+
only the relevant specification
+
one coherent milestone
```

This preserves context and lets Astra spend its tokens on implementation.

## 10. Final architecture to show a professor

```text
SEBI IPO filings
  ↓
Versioned ingestion + amendment lineage
  ↓
Docling / OCR
  ↓
Entities + tables + evidence
  ↓
Entity resolution
  ↓
Candidate facts / relations
  ↓
Evidence + context hard gate
  ↓
Accepted historical observations
  ↓
Amendment-aware active/as-of view
  ↓
PostgreSQL (authority)
  ├── Neo4j (corporate graph)
  └── pgvector + BM25 (retrieval)
  ↓
M1 Corporate Intelligence
  ├── M2 Comparison
  ├── M3 Financial Learning
  └── M4 Virtual Portfolio
  ↓
React dashboard
```

## 11. Final demo story

Do not demo twenty disconnected features.

Use one company and one relation as the narrative:

1. Upload a real filing.
2. Show the extracted company relation.
3. Open the exact evidence.
4. Show the ownership/value/period context.
5. Introduce the amendment/addendum.
6. Show historical vs active view.
7. Ask a source-grounded question.
8. Compare the company with another company.
9. Open a financial term.
10. Show a deterministic virtual portfolio scenario.

That tells one coherent story: **from filing to validated intelligence to learning.**

## 12. Final decision

Do not begin full Astra implementation until:

- the midsem architecture slide is reconciled with the final stack;
- ECRE wording is replaced by the amendment-aware research framing;
- four retrieval arms are consistently named;
- M1/M2 API ownership is corrected;
- corpus scope is fixed;
- the old WSL2/Next.js/FAISS-Qdrant/FinBERT-SpERT contradictions are removed;
- the compact Astra execution files are present.

After these changes, the project is ready to move from architecture to implementation.

## 13. Supporting sources

External sources should be cited in the final paper for technical capabilities and related work; project claims must come from actual measured runs.

Useful verified sources include:

- SEBI Investor Survey 2025 for the broad financial-awareness motivation.
- Xu et al. 2024 for financial causality KG work.
- Gijre et al. 2024 for KG-assisted document QA.
- Jasmin et al. 2025 for financial RAG, company/year filtering and hybrid retrieval.
- Current GraphRAG/capital-markets work as novelty counter-evidence.
- Official documentation for Gemini structured output/model availability.
- Official pgvector, Docling, Neo4j and BGE documentation.

Do not convert any of these technology/research references into claims about RegIntel's own performance before running the project.
