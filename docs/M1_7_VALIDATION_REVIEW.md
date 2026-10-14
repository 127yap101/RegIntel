# M1.7 — Mandatory validation and staged review

This execution record describes the bounded gate implementation. Verification,
primary activation and publication status are recorded in CURRENT_STATE and the
measured validation report only after actual checks pass.

## Authority boundary

Original candidates stay immutable `CANDIDATE` records. Separate gate runs use
`PASS`, `REVIEW` or `QUARANTINED`; these are validation outcomes, not accepted
corporate observations. An administrator can record `APPROVE_FOR_PUBLICATION`
or `REJECT`. Approval stages eligibility only and cannot override a failed or
unresolved mandatory check.

All existing acceptance-audit, fact/relation observation and corpus insertion
gates remain closed. Research method §10 requires a corpus version for accepted
observations; M1.9 will revalidate staged decisions and create immutable
acceptance/observation/corpus state through its publication transaction. No
placeholder corpus, graph projection or retrieval authority is introduced here.

## Inputs and checks

Only owned sealed M1.6 candidate runs can be validated; bare0003 placeholder
rows are excluded. A validation run binds the original candidate/input bytes,
exact original-text evidence and geometry, current entity decisions, current
numeric policies and server-derived table/transcription risk IDs. Historical
audits remain separate and queryable. New approval requires the current
validator configuration and unchanged dependency snapshot.

Every result includes sixteen explicit check categories, with inapplicable
checks marked as such: source membership/support, effective entities, table
context, source scope, attribution, direction, metric semantics, raw value,
unit, currency, period, basis, denominator, stake kind, ownership date and
extractive narrative review. `FAIL` quarantines; unresolved checks route to
review with approval blocked. Only the extractive-confirmation check may remain
`REVIEW` on a candidate eligible for an explicit administrator decision.

The complete source statement and surrounding original-text block are checked
for instructions, illustrative scope, attribution, negation and conditions.
Relations require a narrow directed affirmative grammar. Unsupported direction
is quarantined; ambiguous/speculative/quoted/temporally qualified relation
semantics cannot become an unqualified edge. Numeric values must bind to their
own metric clause, rather than borrow another amount's unit/period/basis.
Conditional extractive narrative text can preserve its qualifications; it never
becomes an assertion that the proposed event already happened.

Processed table geometry is used solely to detect risk. Overlapping original
text, unavailable geometry or unresolved page mapping withholds approval where
exact original row/header/cell context is absent. Missing geometry widens the
review region conservatively; it never creates a table cell or financial fact.
OCR origin is likewise a transcription risk, even for syntactically plausible
numbers. Source-image transcription review is not implemented; OCR/unknown
quality cannot be reviewer-overridden through this gate. No OCR confidence or
research accuracy is invented.

## Financial interpretation

Extraction cues alone do not define numeric meaning. A separate immutable
`NumericMetricPolicy` binds an existing numeric metric to MONEY, COUNT, POWER or
PERCENTAGE, expected instant/duration period, controlled allowed units and
whether reporting basis is required. This is gate configuration, not M2
comparison formulas or a claim about a company.

The backend parses raw signed/parenthesized Indian or Western grouped numbers
using exact `Decimal`; float inputs, exponent syntax, malformed grouping,
dash/blank and excessive digits fail. Normalized values remain proposed gate
interpretations until later acceptance. Scale labels are preserved without
unit-multiplier arithmetic. Explicit supported currency is required for money;
ambiguous currency glyphs do not silently select a country/currency. The explicit
currency and unit must also agree; USD with a rupee unit is quarantined even when
both labels separately match their syntax/policy.

Instant dates and both duration boundaries require exact source text. A
year-ended label supplies an end date only; the start remains unknown and
approval is withheld. Publication dates never become financial periods. Units,
dates and standalone/consolidated basis must belong to the same source claim.
Ownership percentages additionally need a denominator, explicit ownership date,
stake kind and applicable ownership basis. Direct/indirect ownership basis is
distinct from consolidated/standalone reporting basis; shared basis remains
`UNKNOWN` when only the exact ownership label is supported. Missing context is
not fabricated or defaulted.

## Storage and review

Append0008 only after meaningful fresh-database tests and review. Preserve
applied0001–0007 and the M1.6 source/configuration hashes. New policies, gate
runs and review rows retain strict typed payloads, byte/configuration hashes,
administrator/auth-version audit, complete candidate membership and immutable
history. Stored-current gate runs are rederived from the sealed artifact;
server-side approval reloads current source decisions/policies and rechecks
eligibility. Exact replay retains the original decision ID and payload.

One final decision is allowed per candidate across validation runs. A different
decision or audit ID conflicts. This one-shot stage does not implement flexible
correction of final reviews; supported new proposals/revalidation are required,
and later correction/publication workflows must preserve audit history. Review
support includes the exact complete original primary statement, with all
additional support contained in that statement. New evidence cannot override
an earlier mandatory failure without supported new extraction/validation.

Admin endpoints:

- `POST /v1/admin/validation/policies`: register/replay numeric semantics.
- `POST /v1/admin/validation/runs`: `{candidate_run_id}`; derive all checks.
- `GET /v1/admin/validation/runs/{run_id}`: original gate run and separate reviews.
- `POST /v1/admin/validation/reviews`: staged decision and exact support/note.

Clients cannot supply checks, validator settings, normalized interpretations or
acceptance/publication results. Protected endpoints use the shared envelopes,
request IDs, parse version and no-store responses. Corpus version remains null.
Authentication precedes storage; writes recheck the active administrator and
auth version transactionally. Errors are fixed sanitized messages.

## Verification scope and later work

Tests must include positive cases together with controlled invalid and ambiguous
cases, current/stale reviews, dependency changes, injection, wrong direction,
OCR/table risk, numerical precision, invalid units/periods/basis/denominator,
immutable storage, rollback, concurrent/replayed decisions and JSON read-poison
prevention. Fixture correctness does not establish accepted precision, research
effectiveness or filing-wide OCR accuracy.

The controlled real source currently has one proposed-public-issue narrative,
not real numeric/ownership positives. Runtime verification must report its actual
outcome; it cannot fabricate positive financial observations. M1.8 worker stage
recovery, M1.9 lineage/effects/publication, admin screens, common model tuning and
held-out evaluation remain later work. No provider call, SDK, budget usage,
dependency, system configuration or public port is introduced by this stage.

## Actual controlled runtime — 14 October

Reviewed0008 is primary-applied; migrations1–8 are applied, none pending. Its
SHA256 is `7f739c54b0ed7b7049b22fa3a6d2bbfb780afa84d165913d2b710b9b12fec66d`.
Migrations0001–0007, frozen candidate/parser/entity inputs and dependencies are
unchanged. The new86 live validation cases pass176.03s in a fresh disposable DB;
only that generated DB was removed. Full regression/publication remains pending
until recorded in CURRENT_STATE and the report.

The controlled native HTTP proof uses the original Premier source, parse and
M1.6 candidate run. Gate run `f93660f2-c589-4cc5-af3d-031e896a4d3b` has one
`REVIEW` result with only `EXTRACTIVE_REVIEW` unresolved. All other applicable
checks pass. The exact issuer statement retains proposing, approvals and market
conditions; the staged decision `5c42296e-e63f-4f84-9c52-ead243b9596c` records
`APPROVE_FOR_PUBLICATION` as engineering eligibility only. The original candidate
remains `CANDIDATE`; it is not an accepted observation or independent gold review.

Across878 exact inputs,628 are conservatively classified as table risks and11 as
transcription risks; these are risk counts, not error rates. The selected complete
narrative has neither risk. Validation/read/review replay, original evidence read,
anonymous/learner denials and unchanged earlier source/job/entity/candidate/policy
snapshots pass. All four acceptance/observation/corpus counts remain0. The owned
8011API was stopped. Source-containing run/review payloads stay ignored under
`.cache/validation-runtime-df988c475ee74e01bd161fd7c64d0ee8`; publishable metadata
is in `data/validation-review-report.json`.

To reproduce after restoring the controlled local source and actual database IDs,
start the documented authenticated native API, then run:

```powershell
.\backend\.venv\Scripts\python.exe scripts/check-validation-runtime.py --api-base http://127.0.0.1:8000 --candidate-run-id 6311f8bd-d49d-4fa8-b038-817205e73fff --stage-review
```

Without `--stage-review`, the helper validates/replays/reads without requesting a
review decision. It is confined to the existing complete narrative probe and
loopback API. A different source or a missing controlled asset fails explicitly.
Fresh-clone readers must use their own actual IDs; this machine's database and
original PDF are not distributed through Git.

### Final-code revalidation and preserved review

The initial full default run passes1683backend/6Windows skips,212frontend and
3Chromium checks; the full fresh database suite passes398cases in906.18s. Root
then demonstrated a synthetic USD/rupees pair that was individually well-formed
but semantically incompatible. The joint currency/unit gate now quarantines it;
supported INR/rupees and INR/USD scale-label positives remain eligible. Added
quantity, gate and live approval cases test both outcomes. Final expanded checks
remain pending until their actual results are recorded.

The final code revalidates the unchanged real proposal as gate run
`97ec299b-f5e7-4043-9fec-e7c08473b6a9`, configuration SHA256
`f01505a3ffeec4b6fdd8df78a84dc735fc370348ec539e23198545de37b2996d`.
Its only unresolved check remains extractive confirmation. The original final
review is retained on `f93660f2-c589-4cc5-af3d-031e896a4d3b`, with original
configuration `8f6fb74d99a3aacc6d865432fd8b51d5fa96f91745bcea0fcfd8225cd1029411`.
Exact review replay is a no-op; no second review or history rewrite is performed.
The report explicitly marks `review_recorded_for_current_configuration: false`.
M1.9 must freshly revalidate the candidate and recorded decision before any
acceptance/publication. A readable historical approval alone cannot publish it.

Fresh HTTP proof `.cache/validation-runtime-5ac865911dbd4458b21640e3be538444`
passes current validation/read replay, original review read/replay, exact source
qualifiers, permissions and preservation; all authority counts stay0. The helper
retains an existing matching complete final review across code updates and
reports both configurations. A conflicting final review fails rather than being
replaced. The owned API is stopped and the earlier proof remains intact.

## Final local verification

Final `scripts/run-checks.ps1` exits0:1691backend passes with six disclosed Windows
platform skips,212frontend passes and3Chromium passes, lint/types/build, Ruff141
and strict mypy88. Linux-platform mypy73 and both runner syntax checks pass.
Final fresh90validation database cases pass307.90s, including the four new actual
currency/unit staging cases; their disposable database is removed. Before that
repair, the full398database suite passed906.18s, preserving the312earlier cases.
No claim that a final full402case local run occurred: the final new phase was
verified separately. Hosted CI will run the complete final suite and its actual
result must be recorded after publication.

M1.7 is complete as this bounded original-text validation/review stage. Exact
table-cell/OCR transcription adjudication, flexible final-review correction,
worker recovery, amendments/corpus acceptance/projections, admin UI and research
measurements remain explicit later work. No dependency or environment change.

## Published source verification

Source commit `5de23f585d156fbb4c98564dfc3c083faeefd42d` is on existingmain;
remoteSHA matched and28staged files passed secret/asset/exact-byte review. Hosted
[run38596123035](https://github.com/127yap101/RegIntel/actions/runs/38596123035)
completedSUCCESS forWindows/Linux foundation andLinux data infrastructure.
Windows1694pass/3POSIX skips andLinux1696pass/1Windows-junction skip are actual
hosted counts; native Windows1691/6skips remains the separate local result.

The final complete402database cases pass224.33s on the fresh Linux CI database;
only that generated DB is removed. Fresh migrations1–8 and no-op replay,
authentication and service-restart persistence pass. This supplies the final full
suite result; the earlier398local and final90local checks remain distinct records.
The publication-record follow-up changes documentation/report metadata only;
tested product/migration fingerprints are unchanged. No PR or worker rebuild.
