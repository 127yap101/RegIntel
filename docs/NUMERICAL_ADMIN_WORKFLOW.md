# Numerical filing review in the administrator workspace

29 October 2026. This screen connects the existing native numerical review APIs
to the common M1 publication workflow. The resulting published corpus is consumed
by M1 evidence/facts, M2 comparison, M3 filing context and M4 company selection.
It adds no migration, dependency, required environment variable or quote source.

## Prerequisites

Use the current `codex/m2-comparison` checkout and that installation's existing
local credentials, data services and source storage. Follow
[team setup](M1_TEAM_TESTING.md) for a fresh clone and the
[unified publication guide](UNIFIED_NUMERICAL_PUBLICATION.md) for migration 21,
the pinned local embedding/graph prerequisites and publication configuration.
Do not regenerate credentials over an existing database.

The API must explicitly select the native parser runtime descriptor matching
the retained source intake. Add `--numerical-runtime-file` with that actual local
descriptor to the documented `regintel-api` startup command. Omitting it leaves
the numerical endpoints unavailable. The existing backend owns the descriptor;
the browser cannot select a parser or supply source/configuration hashes.

Generate the administrator contracts after updating the checkout:

```powershell
.\backend\.venv\Scripts\python.exe scripts/export-admin.py
```

The screen starts from a saved numerical gate. Source upload, native capture,
approved entity/metric/policy context and exact binding/gate creation remain the
[source-intake workflow](M2_SOURCE_INTAKE.md) and
[bound gate workflow](M2_BOUND_NUMERICAL_GATES.md). A fresh clone has no laptop
gate IDs, private source files or real approvals. Browser test fixtures do not
seed a database or supply a real decision.

## Review, accept and publish

1. Open **Administrator workspace**, sign in with this installation's current
   administrator account and choose **Numerical filings**.
2. Enter the **Saved numerical gate ID**. Optionally enter its saved candidate
   ID to restore the candidate and its recorded acceptance/rejection. Select
   **Load numerical review**.
3. Inspect all 14 gate checks, raw/normalized decimal strings, period and basis.
   Open **Original source words and table context**. Words retain their original
   order as separate spans; table/cell IDs, grid position and page are available.
   A word button verifies the complete selected evidence record, source hash,
   parse configuration and downloaded PDF before displaying its original page.
4. Choose **Confirm complete source context** or **Reject context** and enter an
   explicit review note. Record the decision. Confirmation is disabled for an
   unresolved/quarantined gate; a note cannot override a mandatory check. A stored
   context decision is immutable and shown with its actual reviewer and ID.
5. After confirmation, choose **Check current candidate prerequisites**. Inspect
   all 16 checks. A blocked result exposes no candidate-creation action. A ready
   result allows **Save numerical candidate**; its request contains only the
   backend-provided gate and prepared-input IDs.
6. Inspect the saved candidate and explicitly choose **Accept after current
   mandatory checks** or **Reject candidate**, with a separate acceptance note.
   Record this decision. The backend freshly verifies acceptance prerequisites.
   Candidate creation and context confirmation alone do not accept a fact.
7. An accepted decision can **Add accepted numerical candidate to draft**. In the
   existing publication form, select the current published parent, check/create
   the draft and inspect its exact scope. **Publish this approved build** is a
   separate action. Build and final commit recheck eligibility; a duplicate,
   stale or unsupported selection cannot advance the authoritative corpus.

The acceptance record preserves its historical `ACCEPTED_UNPUBLISHED` stage even
after a later publication. The UI calls it a recorded decision; it does not infer
current publication membership from that immutable stage. Publication remains
the common authority. Rejected candidates cannot enter the draft selection.

## Interrupted requests and history

An unavailable/transport/unverifiable write response retains its exact submitted
body and locks its fields and navigation. Use the displayed **Retry the same…**
action. The browser cannot change the note/decision or generate a second actor,
candidate or acceptance ID during this retry. A verified response resolves it.
Explicit HTTP 409 conflicts and 422 validation rejections unlock inspection and
correction, clear the current preparation and require checking stored state.

A missing acceptance (404) is different from unavailable storage (503). After
candidate creation, the screen does not expose a fresh decision form until its
existing acceptance history is verifiably loaded. Save the displayed gate,
candidate and decision IDs. Reopen using the same gate/candidate to restore
history; this performs no new approval or publication.

Credentials, loaded proposals, notes and pending bodies stay in memory. Sign-out
or current-admin revocation clears private state; cancelled reads cannot restore
it. Closing/reloading the browser also clears that memory. Use the retained IDs
and original submitted request to recover stored state rather than inventing a
different decision. Existing immutable decisions cannot be edited in this screen.

## Verification and limits

See [the measured report](../data/numerical-admin-validation-report.json) for actual
test counts and disclosed attempts. The browser fixture is captured from the
owned PostgreSQL/HTTP workflow test and checked against all ten corresponding
Python contracts. It is explicitly fictional: a blank two-page PDF and authored
word/geometry declarations test contracts and source handling, not transcription
truth, real filing accuracy, content approval or financial prices.

The [native amendment workflow](NATIVE_AMENDMENT_SUPPORT.md) now extends the common
publication form with separate original-word identity/reference/effect/date
support. Its authored correction scenarios do not approve actual source material.
The four retained real numerical inputs still need source-backed context and
approval resolution. The seven M3 starter drafts still need real content review.
Real amendment-pair acceptance, actual module acceptance, held-out evaluation
and fresh-clone handoff remain required. Quotes remain unavailable by user choice.
