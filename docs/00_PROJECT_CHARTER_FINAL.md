# RegIntel Finance — Final Project Charter

## 1. Project identity

**Project:** RegIntel Finance  
**Full title:** Evidence-Grounded Regulatory Filing Knowledge Graph & Financial Learning Platform  
**Domain:** Financial NLP, Knowledge Graphs, Evidence-Grounded AI and Financial Learning  
**Team:** Artham — M4 | Parth — M1 | Yash — M2 | Shreya — M3  
**Duration:** Six-week capstone pilot

## 2. Final goal

Build a working web platform that transforms a small, controlled corpus of public Indian securities filings into **validated, source-linked corporate intelligence**, then exposes that intelligence through four connected modules:

- **M1 — Corporate Intelligence:** corporate entities, ownership, subsidiaries/associates/JVs and selected business relationships, with quantitative context, amendment lineage and exact source evidence.
- **M2 — Analysis & Comparison:** period/basis-aware company comparison using published facts and explicit missing/incompatible-data warnings.
- **M3 — Financial Learning:** a reviewed glossary and contextual explanations for learners.
- **M4 — Virtual Portfolio:** a deterministic, risk-free portfolio simulator with an immutable ledger and analytics.

The platform is an information/learning system. It is not a stock-prediction engine and does not provide investment recommendations.

## 3. The central problem

Long public filings contain valuable corporate and financial information, but the information is fragmented across narrative text, tables, footnotes, headings and successive filing versions.

Three failure modes matter:

1. **Extraction error:** the system identifies the wrong company, relation, value or table cell.
2. **Context error:** the system uses the right number with the wrong period, unit, reporting basis or ownership denominator.
3. **Version/evidence error:** a later addendum/corrigendum changes a disclosure, but the system continues to show a stale or unsupported fact without making the source history visible.

RegIntel therefore follows:

**filing → structured evidence → entities → candidate facts/relations → context/evidence validation → review/acceptance → versioned observation history → active published view → graph/retrieval → cited user experience**

## 4. Research contribution

### Final proposed contribution

**Amendment-Aware Evidence-Constrained Corporate Relation Extraction** for Indian public-issue filings.

This is an applied research contribution and evaluation protocol, not a claim that a new neural architecture has been invented.

It combines:

1. structure-aware document parsing;
2. corporate entity detection and canonical resolution;
3. typed relation candidate extraction;
4. quantitative-context preservation;
5. hard evidence/context validation;
6. human review for ambiguous semantics;
7. amendment/addendum/corrigendum lineage and explicit effect handling;
8. immutable historical observations;
9. publication of an active graph view only from validated observations;
10. source-linked evaluation of the resulting system.

### Research question

> How accurately can a source-grounded pipeline construct and maintain corporate relationships across successive Indian IPO filings while preventing unsupported or superseded disclosures from entering the active Knowledge Graph?

### Sub-questions

- Does evidence/context validation reduce incorrect accepted corporate relations and financial facts?
- Does amendment-aware lineage reduce stale-fact errors compared with treating filings as independent documents?
- Does hybrid/graph-assisted retrieval improve supported answers over a dense-retrieval baseline?

## 5. What counts as the contribution

The contribution is **not** “we use Neo4j + RAG + an LLM.”

Those are established technologies and existing work already contains combinations of financial KGs, RAG, document parsing and graph-assisted QA.

The contribution is the measurable protocol that connects them for this corpus:

**candidate extraction → evidence/context gate → immutable observation → explicit amendment effect → active as-of view**

## 6. Pilot corpus

Primary scope:

- SEBI public-issue filings;
- DRHP;
- RHP;
- prospectus where applicable;
- addenda;
- corrigenda.

Current seed corpus in the capstone includes:

- Waaree Energies;
- Premier Energies;
- Vikram Solar;
- SAEL Industries;

with their RHP/DRHP and amendment documents as listed in the midsem deck.

The current listed material is roughly eight source documents. The project target is **about ten filings**, so two additional documents may be added if the schedule permits. Do not expand the company set until the core pipeline works.

Annual reports may be added later, but they are not necessary for the first research slice.

## 7. Explicit exclusions

No:

- stock-price prediction;
- buy/sell/hold recommendation;
- real-money execution;
- live trading;
- uncalibrated financial risk score;
- silent inference from co-occurrence;
- silent conversion of dash/blank to zero;
- period inference from publication date;
- mixing of standalone and consolidated values;
- incompatible-unit arithmetic;
- LLM-controlled publication;
- LLM-controlled accounting;
- automatic claim that a later filing supersedes every earlier disclosure.

## 8. Success criteria

The core end-to-end success path is:

**real filing → upload → parse → exact evidence → candidate relation/fact → validation/review → accepted observation → amendment lineage → published corpus → Neo4j/pgvector projection → company page → exact source-page viewer**

Secondary success:

- compatible/incompatible M2 comparison;
- source-controlled M3 explanation;
- deterministic M4 ledger;
- held-out research evaluation;
- reproducible clean-clone setup.

## 9. Evidence rule

Every authoritative filing fact/relation must resolve to:

- document/version;
- page;
- evidence ID;
- exact text/table/cell support;
- period where applicable;
- unit/basis where applicable;
- acceptance/review audit;
- corpus version;
- lineage/effect information when the filing is an amendment.

A page citation alone is not sufficient.

## 10. Final positioning sentence

> **RegIntel Finance is an evidence-grounded financial intelligence and learning platform that converts long Indian securities filings into validated corporate facts and relationships, maintains their filing-version history, and presents source-linked analysis to users.**
