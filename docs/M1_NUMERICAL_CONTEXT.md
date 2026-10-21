# Joint numerical-context preparation

This implements part of the user-approved [numerical producer prerequisite](M2_NUMERICAL_PRODUCER_PLAN.md).
It links bounded original-word references and inspects their joint context. The
result is an internal preparation proposal. It cannot accept a fact, create
public evidence IDs, approve a review or publish a corpus. M2 still requires
the complete M1 evidence, validation, review and publication path.

## Contracts and source membership

`NumericalContextDraft` links the uploaded filing version, proposed subject and
metric IDs, value cell, row label, period column, issuer/CIN heading, local table
caption and unit header. Optional original-word phrases retain basis, currency
and fiscal definitions. Each phrase contains ordered, contiguous whole native
words from one page. It preserves every individual word's existing geometry;
it does not create a combined exact span, cell rectangle or public `EvidenceSource`.

Bounds are four retained original pages, 256 words per phrase, 1,024 selected
references and 64,000 selected quote characters. Supplied page text is bounded
to 500,000 characters. Missing, duplicate, cross-document or extra pages and
source/configuration/code mismatches cannot silently pass. These are internal
preparation limits; existing upload, worker and published contracts are unchanged.

`NumericalContextRepository.inspect(draft, user)` requires a current active
administrator. It reads sealed preparations, the approved entity registry,
registered metric and immutable numerical policy in one repeatable-read
transaction. The repository re-verifies the physical original PDF. Callers
cannot supply approval snapshots through this entry point. Missing storage,
invalid source and denied access remain distinct failures; secrets and source
text are not included in their error messages.

The pure `inspect_context(NumericalContextInput)` function supports deterministic
engineering verification with explicitly supplied trusted snapshots. It has no
database or acceptance authority. Do not expose it as a model tool or mistake a
caller-authored snapshot for a registered approval.

## Joint inspection

All eleven checks are retained in a fixed order:

| Check | Required support for a supported preparation proposal |
|---|---|
| `SOURCE` | One uploaded source/version, distinct original pages and selected SDK/preparation fingerprints. |
| `EXACT_WORDS` | Complete original native words, exact quotes and original word geometry; OCR/unknown words do not pass. |
| `TABLE` | Complete proposed word membership in the same table, aligned row/header spans, explicit header flags and an unambiguous unmerged value location. |
| `ISSUER` | A complete issuer name/CIN heading matched to one approved company identifier and exact approved name or alias. |
| `METRIC` | The complete literal row cue matches the selected registered monetary duration metric and its policy. A narrative metric is rejected even if its policy is missing. |
| `VALUE` | One complete bounded numeric word parsed with existing exact `Decimal` rules. Dash/blank, malformed grouping, injection and over-limit values cannot become numbers. |
| `UNIT` | An explicit bounded local monetary header and a matching allowed unit in the numerical policy. |
| `CURRENCY` | Explicit INR/USD or a complete matching source definition of the local symbol/alias; competing definitions are preserved as failures. |
| `PERIOD` | An explicit annual column end and a complete, matching issuer fiscal definition that supplies the preceding-year start. |
| `BASIS` | An applicable single standalone/consolidated statement caption; separate basis clauses remain reviewable and conflicts fail. |
| `CONTEXT_SCOPE` | Bounded local caption/unit geometry and a supported issuer statement caption; every cross-page link still requires applicability review. |

Local caption/header support must be above the selected table, horizontally
overlap it and have no closer intervening table. Unit/caption gaps are limited
to 96/160 PDF points. Unavailable geometry, merged cells, ambiguous mappings or
unrecognized scope require review. Industry/peer/competitor captions fail.
Page-wide entity co-occurrence cannot establish context.

The first closed grammar supports annual monetary flows only. It recognizes
the explicit issuer clause that its financial year starts on a stated month/day
of the immediately preceding calendar year and ends on another stated month/day.
An optional complete repeated twelve-month explanation must agree. Both actual
calendar dates and a one-year interval are checked. No April default, filing-date
inference or guessed start is used. Other fiscal definitions, quarters, instants
and unsupported kinds remain unresolved. A separate statement-basis clause and
any cross-page applicability remain reviewable even when dates can be proposed.

Currency definitions must explicitly list the selected alias and agree on
the currency name and country. No exchange-rate conversion or authoritative
arithmetic is performed. Unit/basis qualifiers and exceptions remain source
evidence for later applicability gates; a recognized local header does not waive
them. Preserve complete clauses, including “Unless” and “otherwise”.

## Result and limits

`NumericalContextInspection` retains the draft, all checks and separate draft,
source-input and implementation-configuration hashes. Its identity is
deterministic for those exact inputs. A failed check yields `QUARANTINED` and
no quantity. Unresolved checks yield `REVIEW_REQUIRED`. A fully supported
authored local case may yield `SUPPORTED_PROPOSAL` with proposed Decimal-string
value, unit, currency, period and basis.

Every result has `acceptance_eligible=false`, `review_required=true` and
`mandatory_m1_validation_complete=false`, including `SUPPORTED_PROPOSAL`.
These fields cannot be promoted through the strict contracts. Hashes identify
inputs; they are not signatures or approval. The original read-only inspector
does not persist its inputs. The subsequent [history repository](M1_NUMERICAL_CONTEXT_HISTORY.md)
retains exact inputs/results and original submission under separate storage
fingerprints. Re-running against a changed registry produces a different input
hash and separate history.

No endpoint or frontend flow is added. The original inspection checkpoint adds
no dependency, migration or required environment variable beyond the earlier
page/word migration 12. The subsequent history extension adds migration 13.
Preserve the original M1 manual-test database at 1–11; owned disposable tests
use the current loader through 13.

## Verification and continuation

See [the measured report](../data/numerical-context-validation-report.json) and
the latest phase log for actual source hashes, commands, counts and limitations.
Authored fixtures test engineering behavior; they are not independently
transcribed real-filing gold data, human review or research effectiveness.

Run the pure cases with the locked environment:

```powershell
uv run --project backend --locked --no-sync --offline pytest backend/tests/test_numerical_context.py
```

In a clone with its own documented local configuration, the existing helper
creates and removes only a fresh disposable integration database:

```powershell
uv run --project backend --locked --no-sync --offline python scripts/check-migrations.py --test-file backend/tests/integration/test_numerical_context_storage.py
```

The implementation remains under `codex/m2-comparison`. Preparation inspection
history is now persisted separately. Continue with explicit versioned M1 evidence,
current parse/evidence membership,
mandatory validation, actual review, immutable acceptance and publication.
Preparation capture IDs must never be inserted into public evidence fields.
Only then can independently reviewed real numerical expectations close all six
M2 acceptance categories. Quotes remain unavailable by the user's decision;
M3/M4 are not started by this checkpoint.
