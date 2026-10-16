# RegIntel Finance — Tested Dependency Register

## M1.12 administrator workspace — 16 October 2026

No dependency, lock, migration or environment-variable changes. Reuses the
existing FastAPI/Pydantic/PostgreSQL contracts, React/strict TypeScript, AJV,
PDF.js and Playwright. The generated admin schema/types/authored fixtures have
a separate export included in both bootstraps, check runners and CI; existing
exports remain unchanged. No provider/model call, host install or new service.

Processing configuration remains
`bacb112415f5728f813738f353f6c2765a9f0135177460e9497ab00e445b2dd6`.
The approved private worker retains its existing parser/stage environments;
no rebuild is required for the read-only adapter or administrator UI. See
`docs/M1_12_ADMIN_REVIEW_PLAN.md` and `CURRENT_STATE.md` for verification status.

## M1.11 retrieval/Q&A — 15 October 2026

No dependency or lock changes. Reuses PostgreSQL 16.15/pgvector 0.8.7,
Neo4j 5.26.31/driver 6.4.0, ONNXRuntime 1.30.0/tokenizers 0.23.2 and the existing
hash-checked BGE-small-en-v1.5 revision/assets. Query encoding uses the publisher's
fixed English retrieval prefix; documents retain their frozen v1 embeddings.
BM25/RRF and source/numeric routing are explicit application code. No new
provider SDK, hosted model, environment variable, migration, service, worker
build or paid call. Windows/native and the existing private Linux worker remain.

Separate generated retrieval schemas/authored fixtures are included in both
bootstraps, check runners and CI. Original M0/M1.10 exports remain intact.
Runtime, source/budget bounds and measured results are recorded in
`docs/M1_11_RETRIEVAL_PLAN.md` and `data/retrieval-validation-report.json`.

References: [BGE publisher model card](https://huggingface.co/BAAI/bge-small-en-v1.5),
[BM25 authors' review](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf),
[RRF authors' paper](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf),
[pgvector query documentation](https://github.com/pgvector/pgvector).

## M1.10 published reads/viewer — 15 October 2026

Native Node 24.19.0 and project-local pnpm 11.19.0 are unchanged. The environment's
fallback pnpm is 11.25.0 and was rejected by the existing engine requirement;
all installation/verification uses the existing pinned `.tools/pnpm/pnpm.cmd`.
Windows bootstrap now selects that same local wrapper when present.

| Component | Pinned version | License | Actual scope |
|---|---|---|---|
| pdfjs-dist / PDF.js | 6.4.299 | Apache-2.0 | Authenticated byte rendering with source SHA256 verification, legacy browser build and matching worker |
| Cytoscape.js | 3.34.3 | MIT | Directed published relations, accessible text controls, responsive canvas; included TypeScript types |
| @napi-rs/canvas | 1.0.11 optional transitive | MIT | PDF.js optional Node dependency, browser mapping disabled; no native backend use |

Existing frontend pins are preserved. The redundant external Cytoscape type stub
was removed after the installed package confirmed its own types. PDF.js's modern
build used Map.getOrInsertComputed, unavailable in pinned Playwright Chromium;
the package's documented legacy build provides compatibility. Actual authored
and real Premier browser rendering pass. No custom polyfill or browser upgrade.
Production build retains its large-chunk warning; no check is suppressed.

The 142-package Python lock and native 103 distributions are unchanged. No new
backend package, migration, environment variable, service, worker rebuild,
system install, paid API call or original filing. See the M1.10 measured report
and current state for final verification/source-publication status.

References: installed exact-version package metadata/licenses,
[PDF.js distribution/legacy build](https://github.com/mozilla/pdfjs-dist),
[PDF.js viewport example](https://mozilla.github.io/pdf.js/examples/),
[Cytoscape API and license](https://js.cytoscape.org/).

## M1.9 publication runtime — verified 15 October 2026

Native Windows Python3.12.14 now selects `entities` plus `publication`. The lock
resolves 142 packages, adding only neo4j6.4.0 and pytz2026.5; all 140 earlier pins
are unchanged. The native environment has 103 distributions. No host software,
GPU runtime, new database/service, public port or provider SDK is introduced.
The existing worker image, its 109 parser/77 stage packages and `models/m1a-v1`
mount remain unchanged; this does not claim the worker contains M1.9 source.

| Component | Exact version | License | Measured scope |
|---|---|---|---|
| Neo4j Python driver | 6.4.0 | Apache-2.0 AND Python-2.0 | Existing local5.26.31 server; scoped rebuild/verification test passes |
| pytz | 2026.5 | MIT | Neo4j dependency; installed/locked |
| ONNX Runtime CPU | 1.30.0 | MIT | Existing parser pin reused natively; local384-dimensional CLS inference passes |
| Hugging Face tokenizers | 0.23.2 | Apache-2.0 | Existing parser pin reused; exact local token counting without truncation |
| NumPy | 2.5.3 | BSD-3-Clause | Existing native pin preserved; embedding-only pooling/normalization |
| BAAI/bge-small-en-v1.5 | revision5c38ec7c405ec4b44b94cc5a9bb96e735b38267a | MIT | Five pinned assets verified, native CPU inference; no effectiveness claim |

The five ignored model files total133,805,871bytes. Their source size/SHA256 or
Git-blob hashes are checked before installation; final SHA256 values are recorded
in `data/embedding-model-manifest.json`. Canonical manifest SHA256 is
`b0a7456447a70c80769c3cd64c8f92f0d3fb88bb8e55e0d8816436c88edec800`.
The ONNX model is133,093,490bytes, SHA256
`828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35`.
No remote Python model code or API key is used. Actual real-source activation, exact token-bound checks, repeatable CPU inference and hosted Windows/Linux checks pass; details and the disclosed native storage retry are in CURRENT_STATE and data/publication-validation-report.json. macOS/ARM execution and research effectiveness are unmeasured.

Primary references: [driver compatibility](https://neo4j.com/docs/python-manual/current/install/),
[Neo4j6.4.0 metadata](https://pypi.org/project/neo4j/6.4.0/),
[pytz2026.5](https://pypi.org/project/pytz/2026.5/),
[ONNX Runtime1.30.0](https://pypi.org/project/onnxruntime/1.30.0/),
[tokenizers0.23.2](https://pypi.org/project/tokenizers/0.23.2/) /
[upstream Apache2 license](https://github.com/huggingface/tokenizers/blob/main/LICENSE),
[immutable BGE model card](https://huggingface.co/BAAI/bge-small-en-v1.5/blob/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a/README.md).

## M1.8 checkpointed processing/recovery — 15 October 2026

No new dependency pin, operator environment variable, provider/model, paid call or host
software. The 140-package lock and native 92-distribution environment are unchanged.
The approved single Linux worker now has two exact environments: the original
109-package parser environment and a 77-package production `entities` environment.
The latter matches the existing locked Linux entities export exactly, including
spaCy3.8.16/RapidFuzz3.14.6 and their previously documented licenses. One fixed
subprocess runs stage jobs; no new service, worker port or native Windows Celery.
Both environments contain 82 identical current source files.

Final image `5ea1bac10eb3ffdbfe7c3c060763b233f11f85a7096dec790f53243f46c1711b`
uses the existing Python3.12.15/uv0.12.23 base digests and offline Debian closure.
Unchanged parser processing/SDK/model identities pass offline with no intercepted
Python connections; parser package manifest 31dd0ebc... and full exact inventories
are recorded in `data/processing-recovery-report.json`. The stage package manifest
is 61fc644e5639c1960a7bdefd45a2368788357eb130d4025bb0d2cfb45118b31c.
Runtime remains UID 10001/read-only, drops ALL capabilities, no-new-privileges and no
published port; source/model/configuration mounts remain read-only.

Append0009 and corrective0010 are applied/frozen; earlier migration/algorithm
bytes remain unchanged. The correction preserves a failed real probe and compares
sorted evidence membership separately from source traversal order. Final 42 live
recovery cases and two real SIGKILL recoveries pass; local full 441 database cases
passed before the final refinements. Full runner 1747 backend/6 Windows skips,
212 frontend/3 Chromium and final scoped static checks pass. Source commit80f4127 passes hosted [run38686295756](https://github.com/127yap101/RegIntel/actions/runs/38686295756)
on Windows and Ubuntu foundation and Linux data infrastructure, including the
complete final database suite, fresh1–10migration apply/replay andauth/restart
persistence. Publication-record updates change metadata only. No macOS/ARM/fresh real
clone or research-effectiveness claim. See the measured recovery report.

## M1.7 validation/review — 14 October 2026

No added dependency, SDK, environment variable, model, host installation or worker
image build. Existing lock140/native92 and frozen parser-only109 versions remain
unchanged. Migrations0001–0007 and existing source identities remain frozen;
append0008 is applied at SHA256
`7f739c54b0ed7b7049b22fa3a6d2bbfb780afa84d165913d2b710b9b12fec66d`.

Final Windows verification passes1691backend/six platform skips,90final live
validation cases,212frontend/3Chromium/lint/types/build, Ruff141/mypy88; Linux
platform mypy73 and Bash/PowerShell syntax checks pass. Before the final joint
currency/unit guard, the full398live suite passed906.18s; the final expanded90case
suite passes307.90s. Actual final-code source validation, preserved historical
review replay, permissions and unchanged earlier snapshots pass. Financial
acceptance/observations/corpora remain0. Hosted source `5de23f585d156fbb4c98564dfc3c083faeefd42d` run38596123035 is SUCCESS
onWindows/Linux foundation andLinux infrastructure; final402database cases
pass224.33s, migration1–8apply/replay andauth/restart persistence pass. No fresh worker/macOS/ARM or
real-source clone claim. Next is M1.8 stage integration/recovery.

## M1.6 bounded candidates —14October2026

No dependencies, environment variables, model assets, host installs or image builds added. Lock140packages/native92distributions and parser-only109package manifest remainunchanged. Candidate extraction uses the alreadyinstalled entity results and standardPython/Pydantic/psycopg; quantitative interpretations remainnull/UNKNOWN.

ActualWindows fullverification:1378backend/6platform skips,312live database,212frontend/3Chromium/lint/types/build, Ruff126/mypy80; Linux-platform mypy67 and bothshell syntaxchecks pass.0007migration applied/frozen at5385dfda7247aed38dfc152e687a8c5535019e23878a8cc6463ae13b9158f48e; all1–6bytes preserved. Controlledreal candidate replay/evidence/auth/preservation passes. Hosted sourcecommit9ced3a079681bf9cbfae9ad5f2833a1fcf8f26c9 run38552615755 completedSUCCESS onWindows/Linux foundation andLinux infrastructure/migrations. No rebuiltworker/macOS/ARM/freshrealclone claim.

Geminiadapter uses injected transport and65offline mockcases; no SDK/network/model/APIkey/call/cost is configured. RealSDK/version/model/benchmark selection requires explicitbudget and officialcompatibility verification before livecalls. OfficialstructuredJSON/instruction guidance is linked in M1_6_CANDIDATE_EXTRACTION.md; schema compliance never constitutes financial acceptance.

## M1.5 native entity runtime — 13 October 2026

Hosted M1.5 source39ec5f5 verification is now complete: run38407101262 SUCCESS onWindows foundation, Ubuntu foundation and Linux data infrastructure. Actual Linux EntityRuler/RapidFuzz tests and all migration contracts pass. Parsing-only exported109package/version pairs exactly match the retained SDK manifest and contain no entity packages. Historical parser image remains unchanged; no new image/macOS/ARM/full real-filing fresh-clone result is claimed.

The phase-required native production `entities` extra supplies spaCy3.8.16 and RapidFuzz3.14.6, both MIT. Bootstrap and CI select this extra; the parser worker continues selecting only `parsing` so its frozen parser package manifest is not expanded by the entity packages. Official Python3.12/Windows amd64/Linux wheel metadata was checked before installation: [spaCy](https://pypi.org/project/spacy/3.8.16/), [RapidFuzz](https://pypi.org/project/RapidFuzz/3.14.6/). The frozen lock resolves140packages; actual native Windows installation contains92distributions. Existing unrelated versions, including NumPy2.5.3/Pydantic2.13.5/Typer0.26.8, remain unchanged. NumPy arrives through spaCy's numerical implementation and does not feed authoritative financial arithmetic.

Actual native EntityRuler/RapidFuzz imports and resolver tests pass. Use a [blank English pipeline](https://spacy.io/usage/models) with [EntityRuler](https://spacy.io/api/entityruler), without a pretrained pipeline, transformer, GPU or model download. The existing Windows redistributable sufficed; no system compiler/runtime installation occurred. The retained M1A Linux image remains the historical frozen parser runtime and has not been rebuilt with this source/lock. Do not claim its installed package inventory matches the new native entity runtime. Linux entity execution and final hosted checks will be recorded when measured. No new environment variables or provider spending.

The earlier initial hosted CI failure is resolved for checkpointcb772a8: run38343176243 completed successfully, including Windows foundation, Ubuntu foundation and Linux data infrastructure. Later commits require their own hosted results. Older storage/CI/runtime status paragraphs below are historical; current checkpoints in CURRENT_STATE.md take precedence.

Latest9October closure: M0 and M1A are complete. Current worker8d07 matches all53installed Python source files and project/lock inputs;109packages and frozen processing/SDK/model/backend/code identities pass offline preflight. Primary migrations1-5 are applied with frozen hashes; real Premier PARSED/878exact evidence, eight source HTTP checks, consumed duplicate and persisted CIN highlight inspection pass. Existing source/legacy job/accounts/volumes preserved; ownedAPI stopped and data/worker healthy. M1.4 adds no dependency. Final887backend/138live/212frontend/3Chromium/lint/types/build pass with six Windows skips. C: fell to286MB during export, so task clients were stopped; a complete current image was retained and verified. About394MB free remains; recover disk space before another large export. No data/settings/cache reset/prune or host installation. HostedCI/macOS/ARM/fresh-clone/crash-recovery remain unverified. See data/evidence-validation-report.json. Earlier checkpoints below are historical.

## Historical checkpoints

Updated:2026-10-09. M0 and M1.1–M1.3 complete. M1.4 adds no dependency; its code and reviewed0005 pass887backend/138live/212frontend/3Chromium, Ruff100/mypy65. Six Windows skips are disclosed; separate Linux FIFO rejection passed. Final worker rebuild crashed with a bus error/engine500; current package and real persisted-evidence proof remain pending, primary0005 unapplied. pnpm11.19.0 was restored into project-local ignored Corepack storage after the app fallback changed to11.25.0; no system shim/package dependency changed. No Gemini model is selected or paid call made. Deck waiver/worker approval persist.

## Current M1.3 runtime record

Final9October runtime verification is complete. Rebuilt image6695cab1db9b122412aff5724b92cbb1847fa2066f7882e52e961187d16f7437 runs all four existing PDFs in separate offline Linux processes, seeds11/37/71/101, with one selected processing identity0674ad02f980861fcbc012832345a33fa4863146f00d995d4212dbbf98022f7f and SDKidentity73a44db5cdcbc3d5552d9269f0b5bce1741e28fd632f0a92a6139df1e35b5412. Model/package/backend/code hashes agree, original text/quads/canonical geometry reproduce the inspected captures, and fresh live103tests pass. This record supersedes earlier pending-runtime text below. M1.4 adds no dependency and is currently being implemented.

The frozen lock has123packages; native default sync installs60 without heavy
parsing/GPU dependencies. The approved Linux worker installs109production
packages. First corrected image5176422a5fdc85465e30df27984a4568d284c2521198b7c4187ccae950a59c88
passed isolated CPU import and actual offline conversion under UID/GID10001,
read-only root/models, no capabilities or network. Later source changes require
a rebuild and selected-runtime comparison before M1.3 closure; no new successful
Linux execution is claimed for those changes yet.

| Parsing component | Exact selected version | Actual measured boundary |
|---|---|---|
| Docling Slim PDF/local models/RapidOCR ONNX extra |2.134.0|PDF-only controlled conversions succeed; MIT code|
| Docling Core / parser / IBM models |2.99.0 /7.22.1 /4.0.3|Core2.99 matches parser dependency; tested structured export and Threaded backend|
| RapidOCR / ONNXRuntime CPU |3.9.2 /1.30.0|One English tiny ONNX engine; three fixed weights plus matching dictionary; local-only execution|
| Torch / TorchVision CPU |2.13.0+cpu /0.28.0+cpu|Official explicit CPU index; no CUDA/NVIDIA/Triton/GPU ONNX packages|
| SciPy / Rtree, Linux only |1.18.1 /1.4.1|Actual Docling imports require them; BSD notices/MIT respectively; no host installation|

15selected model/config/card/license files total391535814bytes. Manifest
`c8788bd39485f36507c44a6728a8e6c5a423de62c8de28ad52ed7b67490727d2`
is retained in data/parser-model-assets.json. Immutable Heron commit
8f39ad3c0b4c58e9c2d2c84a38465abf757272d8 retains Apache2 model provenance;
accurate TableFormer uses immutable docling-models commit
fc0f2d45e2218ea24bce5045f58a389aed16dc23 and CDLA-Permissive2.0 model license,
separate from code licensing. RapidOCR assets/version/license are fixed to3.9.2.
Every selected weight has a publisher expectation and locally measured SHA256.

42required Debian runtime libraries/configuration files provide libGL/libglib/
libxcb and their hard dependencies, without recommendations, host software or
base-package upgrades. data/worker-runtime-libs.json retains exact versions,
archive hashes, copyright inventories and signed release/index identity.
52572288compressed bytes are ignored under .cache/worker-debs. The sealed
SHA256SUMS hash is6b889dadc5247b656177fc61d41cb7af80c75a68f8db8d1b709c23fedd11c803.
Container build installs only this verified closure offline. The hardened helper
parses only successful gpgv authenticated plaintext; unsigned envelope prefix/
suffix cannot supply index hashes. Actual42-package replay and38helper tests
passed, with2Windows symlink-privilege skips. TLS/signature checks were preserved.

Actual cold conversion records and complete captures remain in ignored
.cache/parser-probes/20261007-v1. All3fixtures/six pages and the3-page Premier
source converted with zero attempted network connections. All58native fixture
lines match individually; raster page3 matches3/5, with reversed disclosure lines,
garbled title and missing footer. Fixture table shape/header recovery fails;
SDK table cells have processed text only and cannot independently support exact
original-cell evidence. Seven geometry overlays were visually inspected.
data/parser-validation-report.json also discloses a real price-band line whose
native extraction omits three visible rupee glyphs. These are bounded engineering
observations, not research effectiveness or financial-fact acceptance.

Known unordered SDK supported_engines metadata is canonicalized while ordered
lists and optional null metadata are retained. The four historical resolved
configurations then share SDK identity
73a44db5cdcbc3d5552d9269f0b5bce1741e28fd632f0a92a6139df1e35b5412.
data/parser-runtime-config.json binds source limits, selected frame and actual
application code hashes; its native-validated processing identity is
0674ad02f980861fcbc012832345a33fa4863146f00d995d4212dbbf98022f7f.
data/parser-sdk-options.json retains full resolved options/package inventory.
This selected descriptor is pending final Linux cross-process verification.

## Toolchain

| Tool | Version | Evidence / status |
|---|---|---|
| Python, native API/tests | 3.12.14 | Project-local uv-managed interpreter installed with `--no-bin --no-registry`; backend tests use it |
| Python, Linux worker image | 3.12.15 | Digest-pinned official slim-bookworm base; image build succeeded, live worker acceptance pending |
| uv | 0.12.23 | Windows x64 release archive SHA-256 verified; `.tools/uv/uv.exe --version` |
| Node | 24.19.0 | Existing native runtime, `.node-version`; unit/static/build checks pass |
| pnpm | 11.19.0 | Existing executable; exact dependency pins/frozen lock installed |
| Docker CLI | 29.7.2 | Existing per-user installation; engine/services recovered after user Desktop startup2026-10-06 |
| Docker Compose | 5.4.0 | Existing plugin; credential-free project config and live service/restart acceptance pass |
| Git | 2.51.2.windows.1 | Local main branch; project metadata ownership repaired; no commit |

## Backend foundation — locked and checked

| Direct dependency | Resolved version | Purpose |
|---|---|---|
| FastAPI | 0.142.2 | Native authoritative backend/application factory |
| Pydantic | 2.13.5 | Typed validation/contracts |
| pydantic-settings | 2.15.0 | Prefixed environment configuration |
| Uvicorn | 0.54.0 | Local ASGI development server |
| httpx2 | 2.13.1 | Supported Starlette HTTP test client |
| pytest | 9.1.1 | Behavior tests |
| Ruff | 0.16.10 | Lint/format checks |
| mypy | 1.20.2 | Strict static typing |

`backend/uv.lock` pins transitive dependencies and hashes. M0.2 locked bootstrap and unified checks exited0: four HTTP/configuration tests, lint, format and strict mypy passed. Replaced the original direct httpx development dependency after Starlette's deprecation warning; httpx2 follows the installed Starlette code and official TestClient documentation. Current acceptance counts are recorded in the M0.6 section below.

## Frontend foundation — frozen lock and verified checks

| Direct dependency/group | Exact version | Purpose |
|---|---|---|
| React / React DOM | 19.2.0 | Typed foundation UI |
| TypeScript | 5.9.3 | Strict application/configuration typing |
| Vite / React plugin | 7.3.1 / 5.1.2 | Local dev and production build |
| Tailwind / Vite plugin | 4.1.18 | Reusable component styling |
| ESLint / JS config | 10.12.0 / 10.0.1 | Supported lint baseline |
| typescript-eslint | 8.71.0 | Strict TypeScript lint integration |
| React hooks / refresh lint plugins | 7.1.1 / 0.5.7 | React lint rules |
| Vitest / jsdom | 4.0.18 / 27.2.0 | Browser-like unit tests |
| Testing Library React / user-event / jest-dom | 16.3.0 / 14.6.1 / 6.9.1 | Accessible interaction/assertions |
| Playwright | 1.56.1 | Chromium browser acceptance |

All exact direct pins, types and transitive resolutions are in `frontend/package.json` and `pnpm-lock.yaml`. M0.2 frozen installation, lint, typecheck,18 unit tests, build and3 Chromium tests passed. Playwright Chromium141.0.7390.37 (build1194) is installed in `.cache/ms-playwright`; full Windows runner exited0 outside the sandbox because sandbox process teardown stalled. One transitive install-time `whatwg-encoding` deprecation notice and cosmetic color warnings remain. Fresh cache directories resolved the pytest permissions warning; no checks or assertions were disabled. M0.6 extends frontend acceptance to212 unit tests and3 Chromium tests.

## Infrastructure / later phases

M0.3 added psycopg[binary]3.3.6 (both distributions LGPL-3.0-only), actual driver/libpq18.4 verified, transitive tzdata2026.5. Direct python-dotenv1.2.4 (BSD3) parses explicit configuration without interpolation. That milestone passed38 default tests and7 live migration cases; M0.4 extends acceptance to74 default tests and58 live cases against a newly created/removed database.

| Service | Measured version | Actual local verification |
|---|---|---|
| Docker Engine | 29.7.2 | Local Linux x86_64 engine verified after M0.3 socket recovery; startup failure recurred2026-10-06, then user Desktop startup restored healthy existing services |
| PostgreSQL | 16.15 (Debian16.15-1.pgdg12+2) | SCRAM-required authenticated SQL; clean/repeated migrations; NUMERIC exact Decimal probe survived restart |
| pgvector | 0.8.7 | Extension pin verified; distance query returned3.0 |
| Neo4j Community | 5.26.31 | Authenticated Cypher, health and named-volume probe survived orderly container restart |
| Redis | 7.2.16 | Authenticated PING; unauthenticated PING denied; non-root user; AOF/everysec verified; probe survived orderly container restart |

Digest pins measured from image inspection and registry OCI indexes:

- `pgvector/pgvector:0.8.7-pg16-bookworm@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`
- `neo4j:5.26.31-community-trixie@sha256:d9cfe82983d27f5a75b3aaae8f316d04f9a698a3b7f6103a508f7caf8362f255`
- `redis:7.2.16-bookworm@sha256:0637954999d01b7c9ce9167db2da50656e2590d3b884f1c600c5f63bb6e6773c`

All are multiarchitecture OCI indexes with Linux AMD64/ARM64 variants. The engine returned these index digests as image IDs; the measured active platform is linux/amd64. ARM64 and macOS execution are not tested. Container labels preserve human-readable exact tags while the digests pin patches. No original file/source data was involved in synthetic probes; restart acceptance is orderly service/container restart, not crash recovery or a successful full Desktop cold restart. The2026-10-06 startup failure was observed; services are now healthy after user startup. The rejected repeat runtime-directory change was not performed, and earlier backups/volumes are preserved.

## M0.4 authentication — selected before installation, now verified

Official metadata checked2026-10-05: PyJWT2.15.1 (MIT, Python>=3.9), pwdlib[argon2]0.3.1 (MIT, Python>=3.10), python-multipart0.0.32 (Apache-2.0, Python>=3.10), all Python3.12 compatible. FastAPI's official OAuth2/JWT guidance uses these helpers; base FastAPI excludes the form parser. Existing locks had no alternative JWT/hasher. Actual locked install resolved42 packages, adding argon2-cffi25.1.0/bindings26.1.0/CFFI2.1.1/pycparser3.0 without unrelated upgrades/compiler setup.

Explicit Argon2id policy matches the documented current defaults: version19,memory65536KiB,time3,parallelism4,hash32 bytes,salt16 random bytes. Lock transitive argon2-cffi/native bindings and retain their MIT/CC0 notices. No PyJWT crypto extra is needed for fixed HS256.

Actual acceptance:74 default backend tests;58 live auth/migration cases; strict mypy22 sources/Ruff31 files; frontend18/browser3/lint/typecheck/build and full runner exit0. Primary0002 applied then no-op; seed created2 then preserved2, and both-role check/native HTTP login/identity/admin-denial/cache checks exited0. The independent review's UUID constraint fix was tested before primary application. CI is statically checked but hosted execution remains unrun.

Primary references: [PyJWT2.15.1](https://pypi.org/project/PyJWT/2.15.1/), [pwdlib0.3.1](https://pypi.org/project/pwdlib/0.3.1/), [python-multipart0.0.32](https://pypi.org/project/python-multipart/0.0.32/), [FastAPI JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/), [FastAPI form dependency](https://fastapi.tiangolo.com/tutorial/security/first-steps/), [pwdlib Argon2 wrapper](https://github.com/frankie567/pwdlib/blob/v0.3.1/pwdlib/hashers/argon2.py), [Argon2 profiles](https://github.com/hynek/argon2-cffi/blob/25.1.0/src/argon2/profiles.py).

Docling/OCR, EntityRuler/RapidFuzz, embeddings/retrieval and provider SDKs remain uninstalled future-phase dependencies.

## M0.5 shared contracts — installed and locally verified

Ajv8.20.0 and ajv-formats3.0.1 (both MIT) were selected against official metadata
and draft2020-12 documentation on2026-10-05, then installed with exact direct pins
and a frozen pnpm lock. Four packages were added; the backend42-package lock was
unchanged during M0.5. Pydantic2.13.5 remains the structural schema source; the owned Python
exporter adds no generator dependency. Bootstrap/CI generate ignored schema/types
before frontend checks, while the check runner detects drift without writing.

Actual2026-10-06 final acceptance:303 default backend tests,172 frontend tests and3
Chromium tests; Ruff39 files, strict mypy27 sources, lint/typecheck/build and full
runner exit0. Shared parity covers106 curated synthetic cases across20 public
contracts. After user Desktop startup, final58 live cases pass; middleware review
and non-database preflight regression cover the CORS/cache fix. No real-filing
effectiveness or hosted CI result is claimed.

Primary references: [Ajv8.20.0](https://www.npmjs.com/package/ajv/v/8.20.0),
[ajv-formats3.0.1](https://www.npmjs.com/package/ajv-formats/v/3.0.1),
[Ajv draft support](https://ajv.js.org/json-schema.html),
[Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/).

## M0.6 synthetic fixtures — development-only, verified

Exact development pins were selected against official Python3.12 metadata and
licenses before implementation, then frozen in the47-package backend lock:

| Dependency | Exact version | License | Purpose |
|---|---|---|---|
| ReportLab | 5.0.1 | BSD | Deterministic authored PDF generation |
| pypdf | 6.19.0 | BSD-3-Clause | PDF metadata/boxes/rotation and structure/text integrity checks |
| Pillow | 12.3.0 | MIT-CMU | Real image-only fixture page |
| types-reportlab | 5.0.0.20260911 | Apache-2.0 | Strict typing of ReportLab APIs;5.0.0-target stubs checked against used5.0.1 APIs |
| charset-normalizer | 3.5.2 | MIT | Locked transitive ReportLab dependency |

Actual final acceptance2026-10-06:47-package offline lock check, Ruff47 files,
strict mypy33 sources,319 default backend tests,212 frontend tests, production
build and3 Chromium tests in9.1s; the full runner exits0. The58 live auth/migration
cases already passed separately. Three synthetic PDFs/six pages and their
manifest are reproducible on the tested runtime; artifact drift, raw geometry,
native text, image-only content, source references and tampering/path refusal
checks pass. Final pages were rendered and visually reviewed. All18 adversarial
categories are authored scenario data; Python/TypeScript verify current
structural validity without claiming future evidence gates or model behavior.

Bootstrap/CI generate ignored PDFs, manifest and frontend fixture-case data;
verification checks them without rewriting. No production parsing/model
dependency, migration, environment variable, account setup or infrastructure was
added. Hosted CI, ARM64/macOS execution and universal PDF byte parity remain
unverified. No real-filing research result is claimed. At M0.6 closure the deck
gate and a supported Celery worker execution exception remained outstanding.
The explicit2026-10-06 deck waiver and worker approval subsequently resolved these
implementation prerequisites; the deck itself remains unverified.

Primary references: [ReportLab5.0.1](https://pypi.org/project/reportlab/5.0.1/),
[pypdf6.19.0](https://pypi.org/project/pypdf/6.19.0/),
[Pillow12.3.0](https://pypi.org/project/pillow/12.3.0/),
[types-reportlab5.0.0.20260911](https://pypi.org/project/types-reportlab/5.0.0.20260911/),
[charset-normalizer3.5.2](https://pypi.org/project/charset-normalizer/3.5.2/).

## M1.2 upload/jobs — historical installation checkpoint, subsequently verified

The installed backend lock resolves61 packages. Exact `celery[redis]==5.6.3`
adds the approved Celery/Redis transport runtime; `pypdf==6.19.0` moves from
development-only use to a direct runtime dependency for bounded original-PDF
structure checks. This does not install Docling or OCR. Existing database, auth
and synthetic-generation dependencies are retained.

| Runtime dependency | Exact version | License | Current evidence |
|---|---|---|---|
| Celery with Redis extra | 5.6.3 | BSD-3-Clause | Installed in the61-package lock and43-package production worker build; live delivery/restart pending |
| pypdf | 6.19.0 | BSD-3-Clause | Direct runtime pin for PDF structure/page/encryption checks; original bytes remain unchanged |

The worker image build succeeded with43 production packages using
`uv sync --locked --no-dev --no-editable`, uv0.12.23 and Python3.12.15. The native
API/tests retain Python3.12.14. Image build is not live worker acceptance. Native
producer-to-Redis-to-Linux-worker delivery, worker restart, read-only source access
and final M1.2 verification remain pending.

Build-stage and worker-base pins in `infra/worker.Dockerfile`:

- `ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21`
- `python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`

The approved exception is one Linux application worker on the existing Compose
network, with native Windows FastAPI/frontend and the existing PostgreSQL/Redis
services. It runs as UID/GID10001, publishes no port, drops capabilities and mounts
ignored `data/uploads` read-only at `/sources`. No additional broker/database or
host software installation is introduced. Worker build/start/status/restart/stop
commands are documented in `backend/README.md`.

For Unix-host reproduction, the intended public-source permission contract is
0755 for source directories and0644 for public PDF files so UID 10001 can read the
bind mount. This contract is not yet enforced or tested; restrictive native-user
umasks can make sources unreadable. Windows is the measured host target. The
Linux image build does not establish macOS, ARM64 or native-Linux API reproduction.

Docling, the explicitly configured OCR engine, NLP/embedding/retrieval packages
and Gemini/provider SDK/model artifacts remain uninstalled. No parsing/model
result, paid call, real-filing evidence acceptance or research improvement is
claimed.

Primary references: [Celery5.6.3](https://pypi.org/project/celery/5.6.3/),
[Celery Redis transport](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html),
[Celery Windows support](https://docs.celeryq.dev/en/stable/faq.html#windows),
[pypdf6.19.0](https://pypi.org/project/pypdf/6.19.0/).
