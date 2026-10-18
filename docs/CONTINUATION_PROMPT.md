# Continue RegIntel from the M2 comparison checkpoint

Work on `codex/m2-comparison` in https://github.com/127yap101/RegIntel.
Inspect Git/remote/environment and read AGENTS.md, CURRENT_STATE.md,
docs/M2_IMPLEMENTATION_PLAN.md, data/analysis-validation-report.json and the
newest PHASE_LOG entry. User explicitly authorized M2 on17October and continuing
implementation/testing/commits/GitHub updates. Do not repeat the deck waiver,
Windows exception or private Linux worker approval.

The local isolated checkout is D:/RegIntel/.cache/worktrees/m2-comparison.
D:/RegIntel remains clean M1 main at236c03f while the user manually tests M1.
Use the existing M2 checkout/branch; do not overwrite the M1 source or stop its
native API/frontend. Browser checks use separate loopback8021/5175 and refuse
server reuse. Another teammate should check out the M2 GitHub branch in their
own clone and use the normal locked setup. Local credentials/corpus/assets are
not in Git. All prior approved local .env/.env.auth use remains programmatic,
localhost-only and secret-free in outputs.

M1/M1C is complete as bounded engineering implementation. Source4114407 passed
exact-source hosted run38908935402. M2 now adds backend/src/regintel/analysis,
frontend/src/analysis and published profile/source integration. POST /v1/compare
consumes one PUBLISHED M1 active/as-of view and the frozen accepted metric/entity
catalog. It selects explicit metric IDs, one complete period and reporting basis,
normalizes supported units with Decimal, preserves conflicts/unknown contexts,
and returns full input observations and exact support/context IDs. An active
unknown period/basis that could apply blocks arithmetic. Different complete
periods do not silently align. No FX conversion or timestamp selection.

Difference = comparison - first selected baseline. Percentage difference =
100 * difference / baseline, positive baseline only, explicitly ROUND_HALF_EVEN
to six decimal places. Exact scaling/subtraction retain wire limits; overflow
is unavailable. Percent input differences use percentage points. No label-based
ratio or browser/model arithmetic. Response bounds are100 accepted inputs and
4,000,000 bytes, without truncation. SourceViewer uses the existing exact PDF/hash
contract. Sessions stay in memory and results clear on logout/expiry/cancellation.

GET /v1/quotes is M2-owned and honestly UNAVAILABLE/NO_CONFIGURED_SOURCE with
no prices/version. The user explicitly chose to keep quotes unavailable for now;
this decision is recorded on 18 October. Do not introduce a feed, provider or paid
usage. M4 snapshots/ledger remain untouched. Overall M2 acceptance is
not closed: real numerical inputs and user testing remain.
Do not begin M3 merely because authored engineering fixtures pass.

All eleven migrations, frozen M1 domain algorithms, final numbered specs,
infrastructure and dependency locks remain byte-identical to the base; the
selected preservation set contains136 files. No new dependency, migration,
required application environment variable, paid/model call or service. Optional
test-only variables REGINTEL_TEST_API_PORT/REGINTEL_TEST_WEB_PORT/
REGINTEL_TEST_PYTHON allow isolated browser execution; CI defaults remain8000/5173.
Bootstrap/check/CI generation includes M2 schemas and labelled authored fixtures.
Generated files, PDFs/models, credentials, caches and database state stay ignored.

Focused verification:55 backend M2 cases;277 complete frontend unit tests,
types/lint/build; four disposable PostgreSQL cases in13.18s. Final-source full regression passes1987 backend/six Windows skips in238.10s
(493 integration cases deselected) and all30 Chromium scenarios. Source
921e6a616ee27d82eb97362aa90cec3298761a95 is pushed to the M2 branch. Exact-source
[CI 39007655529](https://github.com/127yap101/RegIntel/actions/runs/39007655529)
completed SUCCESS for Windows/Ubuntu foundation and Linux data infrastructure,
including complete commands, fresh migrations, authentication and restart
persistence. All 34 measured source fingerprints match the verified commit;
the 18 October follow-up changes documentation/report metadata only.
Do not infer hosted per-test counts from job success. Static checks cover209 Ruff
files/139 mypy sources, all generated artifact drift checks, shell syntax and
workflow validation. The existing large JS bundle warning remains disclosed.

Real read-only proof .cache/analysis-runtime-15dde28887ea4f95acc68a7b72161fc5
verifies corpus614d7861-3f8f-4d5c-a9e5-d7423c2aba58,
manifest6622925d2516aedd4c04194372c7783983b00b14271a9d7edcb7ff5b65cda58e,
original Premier page3/source SHA
a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347,
and unchanged37 state-table hashes. Only one company/conditional narrative is
published; zero real numerical/relation positives, an unresolved parent, effects0
and an unknown publication date remain. No real numerical comparison, actual
amendment-pair, gold/held-out effectiveness or provider selection result exists.
The new positive numerical/PDF cases are authored engineering fixtures only.

Existing PostgreSQL/Neo4j/Redis containers were stopped and restored from original
volumes. The worker was not started/rebuilt; Docker data stays D:/DockerData.
Preserve0011 SHA310b96aec87ff153826cbc0a0edf997becb96a27e487e3624e3c18e2479ad9b6
and processing configuration
bacb112415f5728f813738f353f6c2765a9f0135177460e9497ab00e445b2dd6.
Use Node24.19.0, pnpm11.19.0, Python3.12.14 and locked entities/publication extras.
Read docs/RUN_AND_CHECK.md for normal setup/manual tests. Implement only the
remaining authorized M2 scope, verify meaningful behavior, review the diff,
record limitations and update the branch normally; never force-push/reset.
