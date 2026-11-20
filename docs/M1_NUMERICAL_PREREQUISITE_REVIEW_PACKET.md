# M1 numerical prerequisites: pending reviewer decisions

Prepared 19 November 2026 from the four retained original-installation packets.
**Status: all proposals below are pending.** This document records source locators
and proposed registration fields for human review. It does not register a metric,
policy or company, record a reviewer decision, accept a financial observation or
publish a corpus. No original database write was made while preparing it.

The [readiness report](../data/real-gate-readiness-report.json) records the current
blockers; the [team checklist](TEAM_ACCEPTANCE_CHECKLIST.md) owns the complete
acceptance sequence. The exact packet files are local and ignored:
`.cache/real-review-intake-20261106/{premier-21,premier-22,waaree-9,waaree-10}-gate.json`.
The identifiers below belong to this installation. A fresh clone must load its
own verified sources and records; these IDs are not a portable database seed.

## Decisions needed

| Pending decision | Concrete proposal | What it can resolve |
|---|---|---|
| Common metric | Register the proposed numeric metric `3df220c0-8cb5-483a-8116-7d4c4eb80f25` with the exact reviewed revenue cue below. | `METRIC`, together with its policy. |
| Monetary policy | Review `MONEY`, `DURATION`, unit label `million`, reporting basis required. Allocate a new policy ID only for the eventual explicit submission. | `METRIC` and the current policy-related `UNIT` blocker. |
| Waaree company identity | Review the complete native name/CIN heading and proposed company ID `22961129-2ea8-4667-bd62-7ece45a28629`. | Waaree's `ISSUER` blocker. |

Premier already uses approved company ID
`581d1b0d-98fd-4a23-8e15-5574dac650a2` in the retained snapshots. These prerequisite
decisions cannot resolve cross-page applicability, qualified language or Waaree's
separate basis clause. Those require the subsequent evidence-backed workflow.

## Retained packet and source locators

All four stored gates are `REVIEW_REQUIRED`. Offline replay under the installed
19 November code preserved their checks, quantity proposals and evidence IDs.
Their bound-gate configuration is older; binding, context-inspection and
preparation fingerprints match the installed code. A fresh gate using the same
unapproved inputs would still be blocked. Do not add redundant blocked gates.

| Packet | Stored gate ID | Historical context record ID |
|---|---|---|
| `premier-21` | `1b2fa447-0a6a-4e12-a2e7-6a115a62bfbd` | `2c024cc0-e2bb-4182-88cf-f1accc3f5593` |
| `premier-22` | `029705e3-8f6f-4770-879a-8cb83c64f87f` | `6d5a477f-17e5-4a98-ac35-bf914d35e7aa` |
| `waaree-9` | `e2c4c253-e41c-4091-b7dd-a77f19b7519c` | `4141c3c2-cb70-4d50-a1e8-9cced305e052` |
| `waaree-10` | `d1b75071-d830-4615-a0dc-b02f5d1e806d` | `6ba1db0f-5fa7-4b55-89be-e05c0c03e97e` |

| Source | Filing version ID | Sealed parse ID | Original PDF SHA-256 |
|---|---|---|---|
| Premier | `85c6badf-fbb0-413e-974e-2117c5edb4f1` | `2d2ebe80-0ff1-4c5f-a5ec-2bdc801f5400` | `aeac8f5598627bf5704d0ae714c4ec536570f320cbb552f682a29ed3d3fc14ca` |
| Waaree | `b23a7e66-d8dd-4738-a78f-1c8250072109` | `e95238e7-86c2-482f-a6b5-47efc3ea6087` | `e43eccf533fbe81ebe875f9792d32d4f541570b035d39df17326ead11b8a5c89` |

The [source intake record](M2_SOURCE_INTAKE.md) links the official source listings
and distinguishes filing dates from effective dates. Original PDF display pages
are 1-based; `page_index` and native word indices below are 0-based.

| Source | Table PDF page / index / printed page | Context PDF page / index / printed page | Table capture ID |
|---|---|---|---|
| Premier | 30 / 29 / 26 | 20 / 19 / 16 | `fe8dfc38-c651-4963-a99a-f90b9d31895d` |
| Waaree | 99 / 98 / 95 | 19 / 18 / 15 | `d6b55c37-644e-46d9-a216-0e035df08a9c` |

Inspect the complete original table and definitions, including quarter columns,
footnotes, scope and exceptions. The following are **unaccepted source values**;
the source labels and review proposals do not establish published facts.

| Packet | Column year end | Exact value word | Value evidence ID |
|---|---|---|---|
| `premier-21` | 2024-03-31 | `31,437.93` | `59dee4f3-3cd6-4fd2-a113-80d192d024b1` |
| `premier-22` | 2023-03-31 | `14,285.34` | `88f0cb06-9bc0-4a8e-9524-b04bee9d7196` |
| `waaree-9` | 2023-03-31 | `67,508.73` | `c7206c37-e26e-4f58-b1e9-0db54dbae16a` |
| `waaree-10` | 2024-03-31 | `1,13,976.09` | `871c43d1-31da-4a53-bab4-988eed3bb013` |

## Proposal A: common revenue metric

The two complete row labels are displayed below as ordered original words.
These are inspection labels assembled with spaces, not a new combined source
span. The entire Waaree `(a)` word remains in the retained evidence. The owned
context checker permits this enumerator when comparing the complete row label
with the reviewed literal cue; no source word is deleted or rewritten.

Proposed `MetricDefinition`, not submitted:

```json
{
  "id": "3df220c0-8cb5-483a-8116-7d4c4eb80f25",
  "key": "revenue_from_operations",
  "label": "Revenue from operations",
  "kind": "numeric_fact",
  "cue_phrases": ["Revenue from operations"]
}
```

The ID already appears as an unregistered reference in all four retained drafts.
The key and label above are proposed configuration, not existing registrations.
Check the current metric catalog for a conflicting ID/key or an already approved
equivalent before submission. If an existing different metric is selected,
prepare new context drafts with that actual ID and retain the old records.

Exact row-word anchors; all spans start at zero and end at the displayed length:

| Source | Word index | Exact original word | End | Evidence ID |
|---|---|---|---|---|
| Premier | 108 | `Revenue` | 7 | `5ae1e63d-aa5d-44f2-ac02-1e7c725368c2` |
| Premier | 109 | `from` | 4 | `b7e9f069-7d9e-46f7-a27c-f6316e258d95` |
| Premier | 110 | `operations` | 10 | `90c0f9b6-44be-447f-8ed9-4839c78f869d` |
| Waaree | 42 | `(a)` | 3 | `017f2114-1652-46c1-a4dd-0e2f810385f2` |
| Waaree | 43 | `Revenue` | 7 | `0e27d208-fe48-4061-ad42-e0b9e16afa4c` |
| Waaree | 44 | `from` | 4 | `c4e39ce6-aa45-40dd-b98d-6452dd586d9f` |
| Waaree | 45 | `operations` | 10 | `2068c132-39a4-452c-a991-be3282f624db` |

**Reviewer response still needed:** confirm or correct the proposed meaning,
common metric mapping, literal cue and key. Review the restated statements and
scope; matching words alone do not establish financial comparability. Record the
actual reviewer/date and reasoning in the team review record. The metric API
schema has no `review_note` field; do not invent an unsupported JSON field or
claim that the author of this packet performed the approval.

## Proposal B: matching monetary policy

Proposed `NumericMetricPolicy` fields, not submitted:

| Field | Proposed value or pending input |
|---|---|
| `id` | **Pending:** a new canonical UUID for the actual submission, after checking existing policy bindings. No policy ID is asserted by this packet. |
| `metric_id` | `3df220c0-8cb5-483a-8116-7d4c4eb80f25`, only if Proposal A is approved under that ID. |
| `quantity_kind` | `MONEY` |
| `period_kind` | `DURATION` |
| `allowed_unit_labels` | `["million"]` |
| `required_reporting_basis` | `true` |
| `review_note` | **Pending:** the real administrator's nonblank reasoning, up to 2,000 characters. |

The narrow unit proposal reflects both retained table headers. It does not add
crore/lakh/other scales, infer a currency from a symbol, determine a period from
the publication date or remove qualified-language review. Currency definitions,
fiscal definitions and reporting-basis evidence remain separately retained for
source and applicability review. Current `UNIT` checks require the matching registered
metric policy; a permitted label does not prove every row's applicability.

Ordered header words (inspection display only): Premier
`(₹ in million, unless otherwise specified)`; Waaree
`(in ₹ million, unless otherwise stated)`. The qualifications remain part of
the source. Exact word anchors follow; all spans start at zero:

| Source | Word index | Exact original word | End | Evidence ID |
|---|---|---|---|---|
| Premier | 33 | `(₹` | 2 | `77c4617d-a960-4351-8943-78568271d589` |
| Premier | 34 | `in` | 2 | `2b2704b2-9d61-4f2b-a648-6275ba27e348` |
| Premier | 35 | `million,` | 8 | `fa1974ae-0393-4b3f-a38b-a6c6cc6a6a34` |
| Premier | 36 | `unless` | 6 | `2ac518f7-6697-46d4-a107-ce51dc071a0f` |
| Premier | 37 | `otherwise` | 9 | `3e24954e-145e-4fb7-af4b-afe7129818a3` |
| Premier | 38 | `specified)` | 10 | `6f08e4fe-912e-46f5-adfb-2ca96a1128dd` |
| Waaree | 6 | `(in` | 3 | `3d20cd0c-05cf-497f-b532-28ed798cc31d` |
| Waaree | 7 | `₹` | 1 | `3735e829-a9cd-408e-9d1d-6a20b367bafe` |
| Waaree | 8 | `million,` | 8 | `e1125e74-1d00-4732-b4b6-192144856898` |
| Waaree | 9 | `unless` | 6 | `a4ab8a46-5f99-44ee-8028-bb0f9456243f` |
| Waaree | 10 | `otherwise` | 9 | `e6ba07c3-d72a-46ca-a76b-ad96e283ba3f` |
| Waaree | 11 | `stated)` | 7 | `1f0f8290-ff7f-41b5-b0ec-86fa95a98f01` |

**Reviewer response still needed:** confirm or correct monetary annual-flow
semantics, the permitted unit and the requirement for explicitly supported
reporting basis; provide the actual policy review note. Approval does not turn
these four amounts into accepted observations. Existing policies and their
metric bindings are immutable; a conflicting request must be resolved explicitly.

## Proposal C: Waaree native company identity

Proposed company ID: `22961129-2ea8-4667-bd62-7ece45a28629` (currently only a
reference in these retained drafts). Proposed display name:
`WAAREE ENERGIES LIMITED`. Source CIN: `U29248MH1990PLC059463`.

The exact heading is on original PDF page 1, `page_index=0`, page ID
`5df68c93-6c72-461e-9eb7-ef392b6cf32d`, capture ID
`6634e294-b534-44af-a4bc-5598af54e0f0`. Use the Waaree sealed parse listed above.
All seven native words are separate evidence records; all spans start at zero.

| Native word index | Exact original word | End | Evidence ID |
|---|---|---|---|
| 27 | `WAAREE` | 6 | `ecfa6731-c43f-4f93-8d8a-ef46b29c9d62` |
| 28 | `ENERGIES` | 8 | `5c2300a1-8a76-4fe1-b558-54dd478a4896` |
| 29 | `LIMITED` | 7 | `bb145f18-49da-4db9-9e43-b307f1f92e93` |
| 30 | `CORPORATE` | 9 | `0ce70b2a-9c3c-434a-aad6-ddb1f3bd9274` |
| 31 | `IDENTITY` | 8 | `2d88d63e-cf97-484c-886a-cf598973d812` |
| 32 | `NUMBER:` | 7 | `99ef8ac6-8e7e-4fd8-affb-f44f2a69308e` |
| 33 | `U29248MH1990PLC059463` | 21 | `cf892fe0-efa3-437c-a62c-16035811546e` |

The proposed `NativeCompanyRegistration` is fully specified except for the real
review decision and note:

- `schema_version`: `native-company-registration-1`;
  `id`: the proposed Waaree ID above; `kind`: `COMPANY`;
  `legal_name`: `WAAREE ENERGIES LIMITED`; `aliases`: `[]`.
- `legal_name_support`: `schema_version=native-entity-words-1`, the Waaree
  `parse_version_id`, and the three exact anchors for words 27–29 in that order.
  Each anchor has only its original `evidence_id`, `start=0`, `end` and `quote`.
- `issuer_header`: the same native-word profile and parse ID, with all seven
  exact anchors for words 27–33 in order. Do not concatenate them into a new
  evidence record or omit the original `NUMBER:` punctuation.
- `identifiers`: one entry with `kind=CIN`, `value=U29248MH1990PLC059463`, and
  `support` equal to the complete word-33 anchor.
- `review_note`: **pending actual human review**, nonblank and at most 2,000
  characters. No reviewer identity or assertion is supplied by this packet.

**Reviewer response still needed:** inspect the original cover and exact native
word evidence; confirm or correct this complete legal-name/CIN binding and the
canonical ID choice. Check the current registry and CIN binding first. If the
same CIN already belongs to a different approved company ID, use the supported
existing identity in new context drafts; do not merge, overwrite or silently
reassign identifiers. See [native identity requirements](NATIVE_COMPANY_IDENTITY.md).

## Submission interfaces and subsequent work

These are existing authenticated administrator interfaces. This document does
not call them, provide credentials or authorize an unattended approval.

| Purpose | Existing interface | Input contract |
|---|---|---|
| Inspect metric catalog | `GET /v1/admin/workspace/metrics` | No registration body. |
| Register reviewed metric | `POST /v1/admin/candidates/metrics` | `MetricDefinition` from `candidates/models.py`. |
| Register reviewed policy | `POST /v1/admin/validation/policies` | `NumericMetricPolicy` from `validation/models.py`. |
| Register reviewed company | `POST /v1/admin/entities` | `NativeCompanyRegistration` from `entities/models.py`. |

Registration checks current administrator authority. Identical replay keeps the
original record; changed immutable IDs/keys/bindings conflict. Inspect each
verified receipt before proceeding. These endpoints do not accept or publish
financial observations.

After genuine registration decisions:

1. Load the current registry/metric/policy and source snapshots. Save new context
   records through `NumericalContextStorage.save(draft, user)` and bind them to the
   same verified sealed parses using the existing producer workflow. Old context
   bytes, original words, exact evidence, approvals and gates remain immutable.
   Do not graft current approvals into a historical context snapshot.
2. Run the installed bound gates for the new context IDs. Inspect every check;
   ensure values, periods, raw source, unit, basis and evidence remain supported.
   If any prerequisite is unresolved, keep it unresolved and correct its cause.
3. Inspect current applicability requirements. Premier's remaining recorded
   reviews concern `CONTEXT_SCOPE` and `SOURCE_LANGUAGE`; Waaree also has `BASIS`.
   Eligibility after the proposed decisions is **not yet measured**. No `FAIL`
   and no other unresolved mandatory check can be overridden by applicability.
4. Follow [applicability review](NUMERICAL_APPLICABILITY_REVIEW.md), then the
   independent [context confirmation, candidate acceptance and publication
   steps](NUMERICAL_ADMIN_WORKFLOW.md). Keep reviewer decisions distinct from
   machine checks and preserve historical records throughout.

## Pending response worksheet

| Decision | Review outcome | Corrections / source reasoning | Actual reviewer / date |
|---|---|---|---|
| Common revenue metric | Pending | Pending | Pending |
| Monetary policy and unit | Pending | Pending | Pending |
| Waaree name/CIN and canonical ID | Pending | Pending | Pending |

This packet is an engineering preparation aid. Its source-word mapping was
checked against retained JSON and current request models; it is not a new PDF
transcription review, gold annotation, financial comparability verdict or human
content approval. No new source material, dependency, migration, price feed or
runtime model usage is introduced.
