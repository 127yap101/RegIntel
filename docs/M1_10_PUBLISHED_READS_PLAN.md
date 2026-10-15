# M1.10 — Published reads and source inspection

Started 15 October from verified M1.9 handoff a5432cc. Continuing implementation,
tests and normal commits/pushes to existing main are authorized. The approved
Windows/native API and one private Linux worker arrangement remain in place.

## Scope and authority

Add authenticated company search, facts and directed graph reads. Resolve one
PUBLISHED PostgreSQL corpus at request start; explicit older versions remain
queryable. Every JSON response records that version. Apply the existing
active/historical/as-of engine before selecting companies, observations or
graph edges. Unknown dates return temporal unavailability, never an empty
apparently successful financial result. BUILDING and unknown versions are not
consumer resources. No extraction, validation, publication or applied SQL changes.

Company labels/search terms and metric labels come from the hash-checked frozen
registry and extraction inputs of the observations' accepted validation runs.
Do not read the current global registry as a published company catalog. Return
only identities referenced by the selected published observations. Preserve all
financial context and decimal strings. Paginate search/facts explicitly; bound
graphs and fail explicitly rather than silently dropping relations. Verify the
exact Neo4j projection before serving its approved directed relation view; PG
still controls inclusion and active/as-of filtering. No inferred extra graph hops.

Add corpus/observation-scoped learner evidence and original-PDF GET/HEAD routes.
Authorize current accounts and published observation membership before evidence,
file, range or conditional reads. Check source hash, filing/parse identity and
exact support/context offsets. Historical support requires an explicit historical
view. Retain the existing administrator-only unscoped routes. Reuse the proven
source hashing/range policy; do not expose arbitrary paths or source URLs.

## Bounded explorer

A small read-only filing explorer consumes these APIs: in-memory login, pinned
corpus, company selection, exact fact/relation support, directed Cytoscape graph
and a PDF.js page with persisted evidence regions. This is M1 consumer/source
inspection, not the later M2 financial profile/comparison or M1.12 admin workflow.
Treat all filing labels/quotes as text; never render source HTML or PDF actions.
No token in URLs/storage/logs. Clear private state on logout or expired auth.
Pin the same corpus across all requests, including evidence/PDF requests; never
silently switch the current head during a viewing session.

PDF.js uses page_index + 1 and its viewport transform for unrotated PDF points,
crop boxes and rotations. Clearly distinguish persisted evidence regions from
the exact quoted character span; do not claim character boxes that were not
measured. Verify source SHA256 in the browser before rendering the fetched bytes.
Keep accessible text/source details when geometry/rendering is unavailable.

Phase-required frontend dependencies: PDF.js/pdfjs-dist 6.4.299 (Apache-2.0,
Node >=22.13 or >=24), Cytoscape.js 3.34.3 (MIT) with its included TypeScript definitions. A redundant external type stub was
removed after the installed package confirmed its own definitions. Native Node 24.19.0 satisfies the published requirement.
Record actual resolved versions/licenses and checks in the dependency register.
No backend dependency, migration, environment variable, service, public port,
worker rebuild, paid call or extra real filing is planned.

References: [PDF.js rendering/viewport example](https://mozilla.github.io/pdf.js/examples/),
[Cytoscape API and MIT license](https://js.cytoscape.org/). Registry metadata was
read from the official npm registry before choosing the exact versions.

## Verification

Test positive company/fact/relation reads together with unpublished/cross-corpus
denials, inactive/as-of filtering, missing dates, hash/ownership tampering,
Decimal fidelity, pagination/bounds, graph mismatch/outage and auth revocation.
Exercise real PostgreSQL reads on disposable authored publication fixtures.
Test frontend wire validation, stale requests, escaped source text, credentials,
geometry (crop/rotation/offset), actual PDF.js rendering and source hash failure.
Run relevant full/static/browser checks, then prove the real Premier learner
slice without changing original source/processing/publication snapshots. Its
one narrative and unresolved parent remain engineering limits, not research
effectiveness or a real amendment-pair result. Save measured metadata only,
update CURRENT_STATE/handoff and publish the verified increment normally.

## Measured local checkpoint — 15 October

Implemented read contracts/repository/service/router, shared authenticated PDF
response policy, and the bounded explorer. Frozen accepted registry/metric
inputs and manifest observation membership govern company/fact labels. The
existing Neo4j projection is verified before its direct approved relation view;
the selected PostgreSQL active/as-of IDs determine inclusion. Learner evidence
and original bytes require exact published corpus/observation/support identity.
No applied migration or extraction/validation/publication algorithm changed.

Full native backend: 1830 passed, six disclosed Windows skips, 474 database
cases deselected, 444.52s. Five new disposable PostgreSQL cases pass in 35.25s,
including exact Decimal context and an older corpus after the head changes.
Final frontend release: 225 unit and nine Chromium cases (17.0s), lint, strict
TypeScript and production build pass. Ruff checks/formats 179 files; strict mypy
117 sources and scoped Linux-platform mypy 11 pass. PowerShell/Bash syntax,
actionlint and the browser helper's Node syntax pass. The initial full runner
encountered a PDF.js compatibility failure after its successful backend checks;
the final complete frontend checks pass after selecting PDF.js's legacy build.
No successful single combined runner exit is invented.

Read-only real HTTP proof `.cache/published-reads-runtime-2ce4efd422dd40f1b9b74ad709c2913c`
and real Chromium proof `.cache/published-browser-4cfe3fe97cfe49109e1acaffdec14f18`
pass on corpus `614d7861-3f8f-4d5c-a9e5-d7423c2aba58`. The browser hashes the
196270-byte original, renders page 3 and its persisted region, supports a narrow
screen, returns date unavailability and clears source state on logout. No token
in storage/URLs and zero browser errors. All source, processing, publication and
authority snapshots are unchanged. Owned proof servers are stopped; four
existing services remain healthy. Only metadata is checked into
`data/published-reads-validation-report.json`; PDF bytes/screenshots stay ignored.

PDF.js 6.4.299's legacy browser/worker pair avoids the modern build's unsupported
`Map.getOrInsertComputed` requirement in pinned Chromium. Its optional Node-only
canvas dependency is recorded; Cytoscape 3.34.3 supplies its own types. Native
pnpm remains project-local 11.19.0. No backend dependency, environment variable,
migration, worker rebuild, new service, public port or paid call was needed.

Explicit limits: 1000 direct graph relations, 128 MB aggregate frozen read input,
64 MB browser source and 16 million rendered pixels. Bounds fail explicitly.
Persisted region highlights are not character boxes. Production build retains
its large JS chunk warning; code splitting is future optimization. Real data
still contains one conditional narrative, zero corporate relations, an absent
parent and unknown publication date. No real numeric/amendment-pair, research,
macOS/ARM or fresh real-source clone result is claimed.

Source checkpoint and hosted Windows/Linux/infrastructure verification are
pending. Record their exact SHA/run and measured results before phase closure.
