# Native source intake command — bounded implementation plan

Authorized 3 November 2026 under the continuing M1–M4 integration work. This
closes the operational gap between the existing offline native/page capture
commands and `NativeM1Producer`; it does not change the parser or financial gates.

Implement an explicit local administrator command with separate `check` and
`import` actions. An ignored JSON plan identifies the intact original PDF,
existing parser descriptor, complete native manifest and one to 32 ordered page
captures, with exact file hashes and uploaded filing metadata. Reject duplicate
JSON keys, unbounded/nonregular/linked files, changed bytes and unsupported
geometry. Replay the entire native bank and exact contextual bridge before any
database writes. A successful check is preparation only and needs no credentials.

Import prompts for the existing administrator password and reuses current-user
checks at every persistence boundary. Copy the verified original through the
existing source store, submit a job under the explicit native configuration,
retain contextual captures and seal through the existing producer. Preserve
metadata conflicts and all old source/parse/review/publication history. Repeat
imports must verify the actual sealed artifact and source membership rather than
merely return an old terminal job. Concurrent imports must seal once.

Native imports run in the calling process using retained captures; they do not
invoke Docling on Windows. Add an opt-in caller-owned job submission mode, with
the default existing worker dispatch unchanged. Reject a change of dispatch
ownership for an existing job, so the legacy worker cannot consume a native
import. No new migration, dependency, worker rebuild, service, paid call,
credential file, required environment variable or public port is needed.

Use authored blank-PDF/native-word declarations to verify integrity, current
administrator authorization, repeat/concurrent imports, tampering, conflicts,
failure recovery and absence of financial acceptance/publication writes in an
owned disposable database. Run existing upload/native producer checks and
relevant full backend/static checks. Keep original PDFs, raw captures, plans and
credentials ignored. Record actual results, limitations and handoff instructions
before committing and pushing the tested checkpoint.
