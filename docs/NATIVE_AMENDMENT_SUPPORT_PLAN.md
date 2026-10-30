# Native original-word support for amendment publication

29 October 2026. Continue the authorized M1–M4 integration from `5c93fe3`.
The user permits adapting M1 contracts/data; immutable source, acceptance,
amendment and publication history remain mandatory.

Add an explicit `native-amendment-words-1` support containing a selected parse
and a bounded ordered collection of separate whole original-word spans. Retain
legacy single spans. No combined source quotation, synthetic evidence record,
source identity or financial value is created. Reconstructed text is internal
to deterministic issuer/reference/operation/date checks and is labelled as
ordered words in the administrator interface.

Derive word positions from the verified complete sealed parse, not request
indices, fuzzy matches, page co-occurrence or a model. Require exact filing /
parse/page membership, original native-word provenance, distinct complete spans
and consecutive original indices. Do not skip unavailable intervening words.
Native effect statements must retain bounded complete sentence context; reject
negation, proposed/uncertain wording and unsupported dates. A date sequence must
be a contiguous part of its actual effect support. Missing boundaries or gaps
remain unsupported rather than being overridden by a review note.

Use the existing publication request/build/finalize/head path. Fresh build and
finalization revalidate source membership and word order. Historical observations
and decisions remain readable without changing their bytes; active/as-of views
continue to follow explicit effects. M2–M4 remain consumers of the same published
corpus. Test a complete authored numerical parent/child pair and all inherited
effect operations without claiming real amendment accuracy.

Append migration 22 for equivalent database-level native support and amendment
checks. Preserve migrations 1–21 and every unrelated existing publication guard;
do not relax the general candidate-span contract. Use disposable local databases
for fresh migration, raw SQL bypass attempts, conflict/rollback/history and
cross-module acceptance checks. No primary database migration, new service,
dependency, paid call, quote feed or public port is needed for this checkpoint.

Regenerate shared contracts and update administrator evidence entry/display.
Verify original-word source inspection, whole-span/order failures, context and
date containment, explicit missing-date behavior, access, retries and unchanged
legacy requests. Run relevant backend, owned PostgreSQL/HTTP, frontend and browser
checks. Record actual results, fixture limitations and remaining real-data /
evaluation work before the authorized commit and push.
