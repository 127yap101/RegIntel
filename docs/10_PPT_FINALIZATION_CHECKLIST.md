# RegIntel Finance — Capstone Midsem PPT Finalization Checklist

## Critical slide fixes

| PDF page | Current issue | Final correction |
|---|---|---|
| 20 — Technical Architecture | Shows FinBERT + SpERT, FAISS/Qdrant and React/Next.js, which conflicts with later stack slides | Replace with Docling + OCR, spaCy EntityRuler + RapidFuzz, schema-constrained Gemini candidates, PostgreSQL + pgvector + BM25, Neo4j, FastAPI, React + TypeScript + Vite, PDF.js/Cytoscape |
| 22 — Ownership & Interfaces | Graph API is listed under Yash/M2 while M1 owns the corporate graph in the implementation specification | M1 implements `GET /v1/companies/{id}/graph`; M2 consumes it |
| 24 — M1 Extraction | Good overall, but avoid implying a trained FinBERT/SpERT model | Keep Docling → spaCy/LLM candidate extraction → RapidFuzz/entity resolution → validation |
| 25 — Retrieval | Good, but presentation should explicitly call this four-arm ablation | Show B0/B1/B2/B3 labels consistently |
| 33 — Proposed Methods | Good “established algorithms + measurable extensions” framing | Change the M1 extension text to emphasize amendment-aware evidence resolution and stale-fact prevention |
| 34 — Evaluation | Good baseline design but does not explicitly evaluate amendments | Add amendment-lineage/stale-fact evaluation |
| 36 — Publication | The title is a manuscript/literature-review title | Label it explicitly as “Proposed paper/manuscript title” |

## Corpus wording

Change:

> “3–5 companies and about 10 public English filings”

to:

> “Pilot seed: 4 companies and approximately 8 currently identified SEBI filing documents; target about 10 if schedule permits.”

Then state that the primary corpus is:

**DRHP, RHP, prospectus, addenda and corrigenda.**

## Final research-contribution slide

Use:

> **Amendment-Aware Evidence-Constrained Corporate Relation Extraction**

Then show:

```text
Filing
  ↓
Structure-aware parsing
  ↓
Entity resolution
  ↓
Candidate relation/fact extraction
  ↓
Evidence + context hard gate
  ↓
Accepted observation
  ↓
Amendment lineage + explicit effect
  ↓
Active/as-of corporate graph
```

## Final research claim

Use:

> “We propose and evaluate a source-grounded, amendment-aware extraction and publication protocol for Indian IPO filings.”

Avoid:

> “No existing system does this.”

## Footer numbering

The exported PDF has inconsistent visible slide numbers after page 19. Renumber the final deck sequentially from 1–36 or remove the footer numbers entirely.

## Visual consistency

The final deck should not contain two different technology stacks. Every architecture, algorithm, requirements and implementation slide must use the same terminology and technology names.
