# RegIntel Finance — Final Evaluation Plan

## 1. Two separate evaluation layers

### Engineering correctness

Does the application preserve, validate, publish and display the correct evidence and state?

### Research effectiveness

Does the proposed extraction/version/retrieval method improve measurable correctness over simpler baselines?

A functioning dashboard alone is not research evidence.

## 2. Gold set

Build the gold set from actual pilot filings.

Target:

- 100–200 entity mentions;
- 50–100 relations;
- 50–100 quantitative facts;
- 20–30 amendment/lineage cases if the corpus provides enough real examples.

Report actual counts.

If the corpus cannot support the target, reduce the target and state the limitation.

## 3. Extraction experiment

### Entity

**E0:** dictionary/rule-only  
**E1:** hybrid entity approach

Measure:

- precision;
- recall;
- F1.

### Relation

**R0:** relation-trigger/dictionary baseline  
**R1:** candidate relation extraction + ECRE validation

Measure:

- precision;
- recall;
- F1;
- direction accuracy;
- accepted precision;
- review rate.

## 4. Evidence/context validation experiment

Create controlled errors:

- wrong row;
- wrong column;
- wrong period;
- wrong unit;
- wrong basis;
- missing denominator;
- missing date;
- dash/blank;
- contradictory disclosure;
- wrong source ID;
- modified quotation.

Primary safety metric:

**accepted-invalid rate**

Secondary:

- invalid rejection rate;
- review rate;
- evidence precision.

The benchmark must include positive examples. A system that rejects everything is not successful.

## 5. Amendment-aware experiment

Compare:

### A0 — document-independent baseline

Treat each filing as a separate observation set; no explicit amendment effect resolution.

### A1 — version-aware method

Use:

- filing lineage;
- affected evidence;
- reviewed/deterministic effect classification;
- active/as-of view.

Metrics:

- lineage precision/recall;
- effect-classification accuracy;
- stale-fact rate;
- current-view correctness;
- historical traceability.

This experiment is central because it is tied directly to the actual DRHP/RHP/addendum/corrigendum corpus.

## 6. Retrieval ablation

Four arms:

| Arm | Method |
|---|---|
| B0 | dense retrieval |
| B1 | dense + company/period/basis filtering |
| B2 | B1 + BM25 + RRF + table-aware chunks |
| B3 | B2 + bounded 1–2 hop graph expansion |

Keep constant:

- corpus version;
- question set;
- model;
- top-k/context budget;
- output policy;
- evaluation rubric.

Measure:

- Recall@5;
- Recall@10;
- MRR;
- evidence-support rate;
- unsupported-answer rate;
- abstention correctness.

## 7. Q&A grounding

Compare:

1. context-only/LLM baseline;
2. standard retrieval-based answer;
3. published-fact/evidence-grounded path.

For each question:

- correct;
- partially correct;
- unsupported;
- wrong context;
- correctly abstained.

A citation is correct only when the cited source supports the claim, not merely when a URL/page exists.

## 8. Numeric question protocol

Numeric questions use:

```text
published fact
   ↓
company/period/basis compatibility
   ↓
deterministic formula
   ↓
Decimal result
```

No authoritative arithmetic by the LLM.

If required inputs are missing/incompatible:

```text
unavailable / incompatible
```

## 9. M2 acceptance

Test:

- same-period compatible comparison;
- different periods;
- standalone vs consolidated;
- different units;
- missing metric;
- conflicting observations.

Derived values expose their input facts/evidence.

## 10. M3 acceptance

Test:

- definition correctness;
- source linkage;
- context selection;
- numeric-example correctness;
- optional paraphrase restriction.

A small comprehension test may be performed only after the core platform is stable.

## 11. M4 acceptance

Fixed-price deterministic scenarios:

- buy;
- partial sell;
- final sell;
- insufficient cash;
- oversell;
- duplicate request;
- retry;
- concurrent/conflicting request;
- ledger replay.

Every committed order has one immutable outcome.

## 12. Browser end-to-end acceptance

The primary demo:

```text
select company
  ↓
open corporate graph
  ↓
select relation
  ↓
see relation metadata / amendment status
  ↓
open evidence
  ↓
PDF opens exact page
  ↓
highlight aligns
  ↓
value/context matches accepted record
  ↓
switch historical/current view where applicable
```

## 13. Reporting discipline

Final report includes:

- corpus;
- annotation protocol;
- data split;
- baselines;
- model/version/configuration;
- evaluation metrics;
- confidence intervals where sample size permits;
- error analysis;
- latency/cost;
- limitations.

Do not report synthetic fixture scores as real-world performance.
