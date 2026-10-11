# M1.4 — Atomic exact evidence and protected original sources

Prepared2026-10-09 within the user's existing M1A authorization. Implementation
starts after M1.3 parser/configuration acceptance; this plan does not prove that
gate or require a second deck/worker approval. M1B acceptance/publication remains
outside this phase.

Append0005; preserve applied0001–0004 and legacy SOURCE_VERIFIED jobs. New parser
configuration identity binds source limits, SDK/model/package/backend hashes,
adapter/geometry/SDK/artifact-model code hashes and the calibrated coordinate
frame. A repeated upload under this configuration reuses the existing source and
filing version while creating one new job. Native API imports lightweight
contracts/configuration; Linux worker owns heavy conversion.

Retain the complete canonical ParseArtifact as an immutable bounded BYTEA sidecar
with its SHA256 and parse/source membership. This preserves processed tables,
cells, flags, original/processed text distinctions, raw reported geometry and
unavailable reasons. The existing relational projection stores original pages
and mapped original-text blocks. Its counted tree describes the projection,
separately from complete artifact counts.

Exact TextEvidence requires a known low-level source-cell index, original Unicode
text, explicit native/OCR status, retained raw quadrilateral, calibrated canonical
boxes, matching half-open spans and no unavailable reasons. Assembled SDK boxes
may be clamped and support preview only. Current table cells have no original
text: preserve them in the artifact without populating cells.raw_text, interpreted
header/context links or independent exact table-cell evidence. OCR confidence is
not evidence of transcription correctness, financial context or acceptance.

Keep the existing session advisory lock. Commit RUNNING/attempt before conversion;
convert outside a SQL transaction. In one transaction insert the complete counted
parse projection, exact evidence/boxes, artifact sidecar and PARSED job result.
Deferred completeness/source gates seal the tree. Completed duplicate deliveries
do not reconvert; transient database failure retries; configuration/source/parser
failures use fixed sanitized codes. No overwrite or historical-result mutation.

Provide admin-protected GET /v1/evidence/{id} with exact shared evidence contracts
and source/parse identity. Provide GET/HEAD
/v1/filing-versions/{id}/source.pdf resolving a database-owned storage key, never a
client path. Authenticate before lookup, hashing, conditionals or bytes. Read and
verify one bounded confined regular-file handle; construct the response from
those same bytes. Retain source SHA256, application/pdf and no-store policy.

Implement one inclusive closed/open/suffix byte range, end clamping,416 with
Content-Range bytes */size, stable quoted SHA256 ETag and Accept-Ranges. HEAD
ignores Range and has no body. Valid multiple ranges/unknown units fall back to
the full representation. Nonmatching/weak If-Range falls back to200. Bound header
length and numeral size. CORS must allow HEAD/Range/If-Range and expose applicable
source/range headers. Later publication controls learner access; M1A source access
does not publish a corpus or accept a financial fact.

Verification covers Unicode round trips, assembly/missing-original exclusions,
source/configuration/membership conflicts, mid-tree rollback, immutable sidecar,
late insert rejection, duplicate delivery and preserved legacy jobs. Verify
authentication/revocation before bytes, hash/size tampering, path confinement and
range/conditional boundaries. Review0005 and run disposable live checks before
primary activation. Close with a real worker result, persisted highlight render,
authenticated native full/range response and relevant full checks. Preserve
credentials, accounts, existing volumes and original PDF bytes; no commit/push.
