# RegIntel Finance — M1 Research Method

## 1. Method name

**Amendment-Aware Evidence-Constrained Corporate Relation Extraction**

Short description:

> Extract corporate relationships from Indian securities filings, validate them against exact source evidence and financial context, then preserve filing-version history so an active graph view cannot silently use an unsupported or superseded observation.

## 2. Processing algorithm

```text
FOR each filing:
    1. identify/hash immutable source
    2. parse structure and provenance
    3. extract entity mentions
    4. resolve entities to canonical IDs
    5. generate local entity-pair candidates
    6. propose typed relations/facts
    7. attach quantitative/context metadata
    8. run hard validation gates
    9. ACCEPT, REVIEW or QUARANTINE
   10. link amendment/addendum/corrigendum lineage
   11. classify only explicitly supported fact effects
   12. build immutable corpus version
   13. project accepted observations to Neo4j/retrieval
```

## 3. Step 1 — Structure-aware document parsing

Use Docling.

Retain:

- page;
- block;
- table;
- row;
- cell;
- header;
- source geometry.

Use OCR only on pages/regions where native extraction is inadequate.

Quality signals should identify poor OCR rather than pretending that an unavailable OCR confidence score exists.

## 4. Step 2 — Entity extraction

### Deterministic baseline

- approved company aliases;
- CIN/ISIN when present;
- spaCy EntityRuler;
- known legal names.

### Candidate recall layer

A transformer NER component may be evaluated if required, but it is **not a hard dependency for the six-week pilot**.

The project should not depend on training FinBERT/SpERT-style models unless the gold set and schedule demonstrate that this is feasible.

## 5. Step 3 — Entity resolution

Resolution order:

1. exact CIN/ISIN;
2. exact approved alias;
3. normalized approved name;
4. fuzzy proposal with RapidFuzz;
5. contextual disambiguation;
6. human review when ambiguous.

Fuzzy similarity is never an acceptance decision by itself.

## 6. Step 4 — Candidate relation generation

Initial ontology:

- `OWNS(owner, owned)`
- `PROMOTER_OF(promoter, company)`
- `SUBSIDIARY_OF(subsidiary, parent)`
- `SUPPLIES_TO(supplier, customer)`
- `AUDITS(auditor, company)`
- `LENDS_TO(lender, borrower)`

Candidate pairs are generated from local structure, such as:

- the same sentence/block;
- related table cells;
- explicit relation-trigger patterns;
- bounded neighboring evidence units.

Do not use page-wide entity co-occurrence as proof.

The hosted LLM may propose a typed candidate only from supplied evidence and supplied IDs.

## 7. Step 5 — Quantitative context

For every quantitative fact/relation where applicable, retain:

- raw value;
- normalized Decimal value;
- currency/unit;
- period;
- period type;
- reporting basis;
- denominator;
- stake kind;
- source page/table/cell.

Example:

```text
51%
Company A OWNS Company B
denominator = issued equity share capital
date = 31 March 2026
evidence = page/table/cell
```

If required denominator/date/basis is missing, the candidate cannot be automatically accepted.

## 8. Step 6 — Hard evidence/context gate

A candidate is accepted only if every mandatory check passes.

### A. Source membership

Every source ID exists in the current parse.

### B. Exact support

The evidence supports the entity, relation/value and relevant source structure.

### C. Table context

For numeric table candidates:

- row label;
- period column;
- unit header;
- basis/consolidation header;
- cell location

must jointly support the interpretation.

### D. Temporal context

Do not infer a financial period from publication date.

Distinguish:

- instant values;
- duration values;
- unknown period.

### E. Relation direction

“A owns B” must not become “B owns A.”

### F. Ambiguity

Ambiguous semantics go to review.

### G. Contradiction

Conflicting observations remain separate.

The system does not simply select the latest timestamp.

## 9. Step 7 — Amendment-aware evidence resolution

The filing corpus contains RHP/DRHP/addenda/corrigenda.

For each amendment-type filing:

1. identify its parent filing where explicitly documented;
2. create a lineage record;
3. identify the affected source sections/facts;
4. link affected accepted observations to the amendment evidence;
5. classify the effect only when explicitly supportable:
   - `ADD`
   - `CORRECT`
   - `SUPPLEMENT`
   - `SUPERSEDE`
   - `REMOVE` only where the source clearly establishes removal;
6. preserve the original observation;
7. expose an active/as-of view from the effect graph.

### Critical rule

A later filing does not automatically supersede all earlier information.

Example:

```text
DRHP:
A OWNS B = 51%

Corrigendum:
ownership disclosure corrected to 49%

Historical view:
51%

Active view after accepted correction:
49%

Both remain traceable to their own evidence.
```

The exact values above are only illustrative; actual project facts must come from the corpus.

## 10. Output states

```text
CANDIDATE
   |
   +--> ACCEPTED
   |
   +--> REVIEW
   |
   +--> QUARANTINED
```

Accepted observation requirements:

- evidence;
- context;
- validation result;
- acceptance audit;
- corpus version;
- lineage/effect record when relevant.

## 11. Why the method is stronger than plain RAG

Plain RAG:

```text
question -> retrieve -> generate
```

M1:

```text
filing
-> structured evidence
-> entities
-> typed candidates
-> context validation
-> reviewed observation
-> amendment/version resolution
-> published graph
-> retrieval
-> cited answer
```

The graph is not the research contribution by itself. The researchable contribution is the validation/version protocol and its measured effect on accepted correctness and stale-fact errors.

## 12. Annotation protocol

Construct a manually reviewed gold set.

Annotate:

- entity mention;
- canonical company ID;
- relation type;
- direction;
- numeric value;
- unit/currency;
- period;
- basis;
- ownership denominator/date;
- evidence source;
- amendment lineage;
- amendment effect, where applicable.

Preferred split:

**company/document-group holdout**, not random sentences.

Avoid allowing the same company and identical document templates to leak across development and held-out evaluation when the corpus size permits.

## 13. Research metrics

### Extraction

- entity precision/recall/F1;
- relation precision/recall/F1;
- relation-direction accuracy.

### Context correctness

- value accuracy;
- unit accuracy;
- period accuracy;
- basis accuracy;
- denominator accuracy.

### Validation

- invalid candidate rejection rate;
- accepted-invalid rate;
- review rate;
- accepted precision;
- candidate recall.

### Amendment/version

- lineage-link precision/recall;
- effect-classification accuracy;
- stale-fact rate;
- active-view accuracy;
- historical-lineage completeness.

### Grounding

- evidence precision;
- citation accuracy;
- supported-claim rate;
- unsupported-fact rate;
- abstention correctness.

### Retrieval/system

- Recall@5;
- Recall@10;
- MRR;
- p50/p95 latency;
- API/model cost.

## 14. Core hypotheses

**H1:** Evidence/context validation lowers the rate of incorrect corporate facts/relations accepted into the published corpus.

**H2:** Amendment-aware lineage lowers stale-fact errors compared with a latest-document or independent-document baseline.

**H3:** Hybrid and graph-assisted retrieval improve evidence retrieval/support over a dense baseline without increasing unsupported answers beyond the predefined tolerance.

These are hypotheses until measured.
