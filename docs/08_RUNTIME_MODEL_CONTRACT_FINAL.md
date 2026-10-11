# RegIntel Finance — Runtime Model Contract

## 1. Model role

The hosted model is a **candidate/draft generator**.

It may propose:

- relation candidates;
- narrative facts;
- raw numeric extraction candidates;
- constrained evidence-bound prose.

It may not:

- publish facts;
- decide acceptance;
- calculate authoritative financial values;
- alter IDs;
- invent evidence;
- browse;
- execute trades;
- modify ledger balances.

## 2. Input trust boundary

Every call contains:

1. fixed system instruction;
2. serialized application data.

Source text is untrusted data.

Never concatenate source text into the system instruction.

## 3. Candidate extraction output

Expected structured output:

```json
{
  "numeric_facts": [],
  "narrative_facts": [],
  "relations": [],
  "issues": []
}
```

Every candidate must use only application-supplied:

- entity IDs;
- source IDs;
- allowed relation types;
- allowed metric IDs.

The model does not compute page indices or create citations.

## 4. Numeric extraction rule

The model returns raw source values and source references.

Backend determines:

- Decimal normalization;
- units;
- compatibility;
- formulas;
- acceptance.

## 5. Narrative answer policy

Default:

**extractive, source-cited output**

For generated drafts used in experiments:

- every substantive claim must cite a supplied evidence ID;
- preserve uncertainty, attribution, negation and qualifiers;
- do not reconcile conflicts;
- abstain when support/context is insufficient;
- numeric questions use the deterministic backend route.

## 6. Optional glossary paraphrase

The model can rewrite an already approved definition/explanation.

It must not:

- add outside facts;
- generate new numeric examples;
- alter formulas;
- invent citations;
- alter the approved context.

The application may fall back to a fixed approved template.

## 7. Optional portfolio feedback

Only after a trade is committed.

The model can explain a stored outcome from supplied approved content.

It cannot:

- request/place/modify/reverse orders;
- calculate authoritative cash/holdings;
- recommend buy/sell/hold;
- forecast price performance.

## 8. Required adversarial fixtures

Test:

- prompt injection in source text;
- fabricated evidence IDs;
- modified quotes;
- same number in standalone/consolidated columns;
- lakh/crore mismatch;
- publication date without period;
- dash/blank;
- entity co-occurrence without relation;
- ownership without denominator/date;
- “may” converted to certainty;
- wrong-year evidence;
- undisclosed supplier;
- valid JSON with unsupported claims;
- model timeout/refusal;
- relation direction inversion;
- OCR corruption;
- restatement/amendment conflict;
- paraphrase introducing unsupported claims.

## 9. Provider/version recording

For every evaluation run record:

- provider;
- exact model ID;
- SDK version;
- generation settings;
- prompt hash;
- schema hash;
- input/configuration hash;
- latency;
- token usage if available;
- cost;
- run ID.

Never use a floating model alias for the final held-out result.
