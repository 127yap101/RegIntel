# M1.1 — Ingestion schema foundations

Started 2026-10-06. This records implementation choices before schema authoring;
the finalized specifications remain unchanged. The user explicitly authorized
M1A and waived the presentation gate. This phase defines storage and typed data,
not upload/jobs, parsing/OCR, acceptance/review or corpus publication.

## Recorded implementation choices

- Immutable source blobs are deduplicated by SHA-256. Their storage key is
  `sha256/<hash>.pdf` relative to a future explicitly configured source root.
  No source bytes are written by this phase. Logical filing identity, immutable
  filing versions, and immutable parse versions remain separate UUIDv4 IDs.
- Filing versions retain declared publication/source metadata and an optional
  declared parent version. This is a declaration, not an accepted lineage/effect.
  Unknown company registration is explicit through a nullable canonical entity
  reference and preserved raw company name; entity resolution belongs to M1.5.
- Parse versions retain adapter/version, configuration hash and artifact hash.
  They declare page/block/table/cell/evidence counts; the complete source tree
  is inserted atomically in the parse's server-recorded creating transaction.
  A deferred count check verifies completeness at commit, and later source-tree
  or header-context additions are rejected. Worker/job lifecycle arrives in M1.2.
- PostgreSQL owns explicit page/block/table/cell/evidence records. Composite
  foreign keys bind source versions, parses, pages, tables and contextual cells.
  A logical table may span pages; every cell retains its own page. Table-context
  links name row label, period column, unit header and basis header roles.
- Page geometry uses existing unrotated PDF points/bottom-left conventions,
  zero-based page indices, raw media/crop boxes and rotation. Text evidence uses
  exact half-open Unicode-code-point offsets over an immutable block. SQL checks
  the quoted substring. Boxes are separate page-local records bounded by the
  media box; cross-page support is multiple evidence records.
- Quantitative context retains exact unconstrained `NUMERIC` with finite/bounded
  value checks, raw text, units/currency, period/basis and ownership context.
  SQL does not round through a fixed-scale numeric typemod. Missing remains null.
- Candidates are only `CANDIDATE` in this phase and cannot create accepted state.
  Accepted fact/relation/audit and corpus-version structures reserve mandatory
  source/context/audit anchors. SQL rejects their insertion until a later M1B
  migration supplies the acceptance/publication gates. Immutability also blocks
  update/delete/truncate on authoritative source/evidence/observation tables.
- All new SQL objects belong to `regintel`; applied migrations 0001/0002 are
  unchanged. Migration 0003 is not applied to the primary development database
  in this phase. No dependencies, infrastructure or credentials are added.

## Acceptance boundary

These schemas enforce structural integrity and exact stored-text membership.
They cannot prove semantic support, entity resolution, financial compatibility,
OCR quality, review decisions, amendment effects or research effectiveness.
No accepted observations or published corpus can be produced in M1.1.

Completed2026-10-06.31 typed-model tests and29 new live storage cases pass.
The latter cover auth/account/checksum-preserving upgrades, failed migration
rollback/retry, Unicode exact slices, cross-source membership, raw geometry and
header cells, immutable rows/collections, atomic parse/count/support completeness,
exact NUMERIC/missing values and premature authority guards. Existing live tests
track default migration versions; isolated two-file probe scenarios remain intact.

Final full runner exits0:350 backend tests,87 integration cases deselected,
Ruff51 files/strict mypy35 sources, frontend212/lint/typecheck/build and Chromium3
(36.1s). Separate live helper passes87/350 deselected in61.11s and removes only
regintel_test_m0_3_80c8aa7f9f454ef19ea3ba81b61179a7.47-package lock and contract/
PDF/case drift checks pass. No package/environment variable was added.

Review corrected non-finite crop extents and immutable-collection append gaps.
The creating transaction is forced by a server trigger; savepoints retain that
boundary. Membership/exact-span checks precede the completed-tree insertion
barrier, so failure tests exercise their actual constraints. All new tables remain
in regintel. Applied0001/0002 checksums are unchanged;0003 remains pending on the
primary development database, to activate after review when M1.2 needs it.

0003 raw UTF8/LF SHA256:
aa67358f920784a50ddb7b39fef9e1f9061f3753b0034c2c02f3e338d26a89f6.
After primary application it becomes immutable. Unresolved company identity
remains nullable; later entity resolution must append approved bindings rather
than overwrite immutable filing provenance. Candidate/quantity support may be
created later but its declared membership is fixed; parsed source-tree records
are completed in one transaction before they are exposed.

Delegated review turns reached the account usage limit after identifying gaps;
root finished those repairs, authored model tests, reviewed the SQL and ran actual
targeted/full/live verification. Failed delegated turns are not claimed as final
independent review completion. No checks were disabled. No acceptance/publication
operation or parser effectiveness is claimed by these engineering results.
