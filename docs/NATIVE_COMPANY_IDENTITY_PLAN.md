# Native company identity support — implementation plan

3 November 2026. Continuing the authorized M1–M4 integration from `14d628e`.
Native M1 evidence contains individual original words. The existing entity
registration requires one exact span containing the whole company name, which
cannot represent a multiword native name without inventing a joined quotation.

Add an explicitly versioned native company registration alongside the unchanged
legacy registration shape. Retain each original name/identity-heading word as its
own exact evidence anchor, selected parse and original order. The initial profile
supports a company name and one CIN in a complete explicit name/CIN heading;
additional aliases/identifiers remain outside this bounded profile. Joined text
is used only for deterministic identity inspection and the company label, never
as an exact quotation or new evidence record.

Use the existing registry endpoint, entity table, unique identifier table,
current-administrator audit and immutable replay/conflict rules. An append-only
migration 23 selects the native guard only for its explicit schema; the original
registration guard remains selected for legacy payloads. Check exact spans,
sealed native parse, whole words, source/page/parse membership, consecutiveness,
name/header containment and explicit CIN syntax/context in Python and SQL.
Reuse the existing sealed original-word position inspection; this does not make
publication an independent identity authority or publish any observation.

Registry snapshots and published catalogs must carry both registration types.
Legacy payload serialization must remain byte-identical. Changing the shared
entity model intentionally changes resolver/numerical processing fingerprints:
preserve historical bytes/hashes and require fresh processing for current
acceptance, rather than relabeling earlier gates as current. No previous
migration or accepted observation is edited.

Verify model bounds, missing/reordered/partial/foreign/native-versus-legacy
support, identifier conflicts, current authorization, concurrent/repeated
registration, direct SQL gates and append-only history. Exercise native issuer
registration through the numerical context/gate and shared publication/read
path over explicitly authored engineering sources; retain independent review
and acceptance actions. No real identity/content approval or research gold is
invented. Run affected complete backend/static and owned-database checks, update
state and handoff notes, then commit/push the verified checkpoint. The approved
worker image copies Python source, so background processing requires a source
rebuild with the new resolver/registry code. Verify an isolated image tag without
starting another service. No dependency, service, required setting, quote source
or public port is added.
