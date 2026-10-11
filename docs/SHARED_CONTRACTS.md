# M0.5 — Shared contract decisions and verification

Started2026-10-05; completed2026-10-06 (Asia/Calcutta). Requirements/interfaces/dependencies were reviewed before implementation. Status: complete; local/full/live verification passed. Original specifications remain unchanged.

## Scope and dependencies

M0.1–M0.4 were verified first. M0.5 defines shared types/serialization/envelopes, not working M1 search/evidence/publication, M2 profiles/quotes or M4 snapshot/ledger behavior. No new migration, generated credentials, model calls or corpus/deck work is needed. Reuse existing Python3.12/Pydantic2.13.5 and strict TypeScript5.9.3.

Official metadata verified Ajv8.20.0/MIT and ajv-formats3.0.1/MIT for frontend runtime draft2020-12 validation. The old Ajv6 is ESLint-only. Exact direct pins and four added packages installed successfully with pnpm11.19.0 before coding; sandbox registry EACCES required scoped network escalation. Actual TS/Vite compatibility requires tests/typecheck/build. Generate schema/types with a small owned Python exporter; no extra backend/generator dependency. Backend lock/dependencies are unchanged.

## Wire decisions

- Contract version1.0.0. Canonical lowercase UUIDv4/RFC-variant strings for application/request/opaque version IDs; source SHA256 hashes and integer auth_version are distinct. IDs establish shape only, never source membership.
- Exact relation enum OWNS/PROMOTER_OF/SUBSIDIARY_OF/SUPPLIES_TO/AUDITS/LENDS_TO; directions owner→owned,promoter→company,subsidiary→parent,supplier→customer,auditor→company,lender→borrower. Endpoints use generic entity IDs. Effects ADD/CORRECT/SUPPLEMENT/SUPERSEDE/REMOVE; states CANDIDATE/ACCEPTED/REVIEW/QUARANTINED. SUPERSEDES is rejected rather than aliased.
- Encode approved ownership only: M1 backend company lookup/search, M2 consuming search/profile UI and GET /v1/quotes, M4 immutable quote snapshots. No functioning business endpoint/UI in this phase.
- Meta contains a server-generated request_id, contract_version and typed versions: corpus/filing/parse/glossary/quote/portfolio version IDs. Non-applicable values are null, including auth; no invented corpus version. Response X-Request-ID matches meta; caller values do not become server IDs.
- Success {data,meta}; error {error:{code,message,details},meta}. Envelope existing auth identity endpoints explicitly through response models/OpenAPI. Preserve existing token endpoint success/errors, health and future binary/range/streaming responses as protocol exceptions. Preserve HTTP status/challenge/Allow/CORS/no-store. Unhandled errors are sanitized500. Validation details omit submitted values, raw exception text and dynamic field names.
- Pydantic is the common structural source. Deterministically export JSON Schema2020-12 and TypeScript declarations/brands, enum/direction/ownership constants. Export/check schema drift without overwriting during checks. Ajv validates unknown JSON without coercion/defaults/property stripping; explicit semantic checks cover Python cross-field rules not expressible in JSON Schema. Shared positive/invalid vectors test actual runtime parity.
- Generated schema/types are ignored artifacts under frontend/src/contracts, as required by the operating contract. Bootstrap and CI recreate them from the Python source; the check runner checks for drift without writing. Curated parity vectors are source test data under contracts/parity-vectors.json. No PDF fixtures are generated in M0.5.

## Exact financial and evidence types

- Financial values are Python Decimal internally and finite fixed-point decimal strings on the wire, preserving fractional scale. Reject wire numbers/booleans/exponents/NaN/Infinity; bound to120 integer/120 fractional digits (no rounding/truncation). Internal Decimal values must satisfy the same bounds before formatting. Strict Pydantic Decimal alone is insufficient: JSON numeric inputs can still be coerced, so use explicit validators/schema/serializer. TypeScript keeps branded strings and performs no authoritative arithmetic.
- Quantitative values retain raw text, normalized value or null, raw/normalized unit and currency or null, period/basis, denominator/stake kind/date or null, and source-evidence IDs. Missing/blank/dash does not become zero. Period INSTANT/DURATION/UNKNOWN preserves explicit missing dates/raw label; basis STANDALONE/CONSOLIDATED/UNKNOWN. Unit/denominator/stake-kind labels stay bounded raw strings because final vocabularies are unspecified. These structural types do not implement compatibility/acceptance gates.
- Evidence source carries filing/filing-version/parse-version/page IDs and zero-based page index. PDF.js page=index+1; integers are bounded for exact JS representation. Text spans are half-open Unicode-code-point offsets and exact quote; emoji is a required parity case. Cell references retain table/cell, row/column/span and separate row-label/period-column/unit-header/basis-header IDs.
- Geometry stores positive media-box dimensions, media/crop boxes (negative offsets allowed), rotation0/90/180/270 and explicit unrotated PDF-point/bottom-left convention. Rectangles must be finite with positive area; dimensions agree with media-box extents. Preserve raw crop coordinates; do not assume nonnegative origin or apply rotation twice. Evidence records have page-local boxes; multi-page support is a list of separate records with unique evidence IDs. Source containment/support validation belongs to M1.
- Lineage uses named parent_filing_id/child_filing_id and a bounded raw type label, preserving ADDENDUM_TO/CORRIGENDUM_TO without inventing a complete succession taxonomy. Unknown labels require later validation. Effect references retain affected/new observation IDs, evidence and optional reviewed decision/effective date. No timestamp-derived replacement/effect. All IDs/context require later source/authority checks.

## Verification gate

Test strict IDs/enums/safe integers, exact large/fractional Decimal round trips, explicit missing context, crop/rotation/emoji/cross-page geometry, lineage/direction and shared valid/invalid payload acceptance. Check generated artifacts deterministically and exercise actual frontend validators. Verify enveloped identity/error/OpenAPI/headers while token/health/security remain correct; run default/live/full checks and independent review before advancing to M0.6.

Primary sources: [Pydantic Decimal](https://docs.pydantic.dev/latest/api/standard_library_types/#decimals), [schema generation](https://docs.pydantic.dev/latest/concepts/json_schema/), [validators](https://docs.pydantic.dev/latest/concepts/validators/#json-schema-and-field-validators), [Ajv draft support](https://ajv.js.org/json-schema.html), [Ajv formats](https://ajv.js.org/guide/formats.html), [Ajv TypeScript](https://ajv.js.org/guide/typescript.html).

## Actual verification — 2026-10-06

Generated artifacts and read-only drift check pass. The full runner exits0:
42-package offline lock check, Ruff39 files, strict mypy27 sources,302 default
backend tests,172 frontend tests, production build and3 Chromium tests. The106
shared wire cases cover42 valid and64 invalid payloads across all20 public models.
Independent review found and corrected lone-surrogate error-message parity;
Python internal construction and frontend nested error validation now reject it.
Static actionlint and Bash syntax checks pass. No checks were disabled.

The user started Desktop; existing services are healthy and migration status
validates applied[1,2]/pending[]. No runtime-directory recovery was performed.
The first live run found57 passes and one CORS preflight cache-header regression.
Reordered middleware to context -> CORS -> error sanitization and added a
non-database allowed/denied preflight regression. Final58 live tests pass in29.30s
and the helper removed its owned disposable DB. Post-fix full runner exits0 with
303 backend/172 frontend/3 Chromium tests, Ruff39/strict mypy27 and artifact drift
checks. Independent middleware review found no blocker. M0.5 is complete;
M0.6 may proceed. Hosted CI and other host/platform execution remain unverified.
