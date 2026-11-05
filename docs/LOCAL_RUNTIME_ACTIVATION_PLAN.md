# Local four-module runtime activation plan

Plan established 4 November 2026; activation verified 5 November. Continue the
authorized M1–M4 integration from `48f5efb`. At the start of this plan, the
original Windows installation retained migration 11 and its actual source
files/models; the integration worktree contains migration 23 and current module
code. Starting that worktree currently looks for assets in the worktree, while
starting the old installation does not activate the later modules.

Extend the existing native `regintel-api` command with an explicit
`--asset-project` directory and a read-only `--check` action. Defaults keep the
current code checkout's assets. The selected directory supplies original upload
storage, the configured parser descriptor and the optional publication model.
Existing descriptor/code validation remains mandatory. Database and auth files
stay explicit independent arguments; selecting assets never selects credentials,
changes Python imports or falls back to another installation.

Before constructing the runtime, verify the current checkout's complete ordered
migration history and reject pending/changed/unknown migrations with a safe,
actionable error. Neither normal startup nor `--check` applies migrations, seeds
accounts, starts containers or approves content. Check output distinguishes
configuration/schema validation from model readiness, authentication, worker
delivery, published data and product acceptance. Numerical review still requires
an explicit compatible `--numerical-runtime-file`. No runtime model, provider,
price feed, dependency, service, public interface or financial contract changes.

Test wrong asset locations, descriptor failures, old/tampered schema, secret-safe
errors, check-only behavior, default selection and successful explicit selection.
Exercise the real CLI and API assembly against an owned populated old-schema
upgrade, preserving existing rows/publication and demonstrating M1–M4 routes.
Run affected static/generated checks and independent existing CLI/config tests.

For this laptop, inspect existing service/port ownership before activation. Take
an ignored verified backup of the selected original database, restore and test
the upgrade on an exact owned disposable target before applying the same tested
append-only migrations to the original. Preserve immutable observations, audits,
publication and user records; record exact before/after fingerprints. Reuse the
approved infrastructure, source/model assets and matching processing worker code.
Never stop an unidentified process or clear volumes/credentials. Bind native
services only to loopback and report actual tested scope. Real filing/content
approval and evaluation remain separate team work. Update measured state/handoff,
commit and push the tested checkpoint.

The implementation and original database upgrade are now verified. The existing
worker selects the matching image, and current native API/frontend browser reads
pass with original assets. See `LOCAL_RUNTIME.md` and
`../data/local-runtime-activation-validation-report.json` for measured scope,
preserved history, source hashes and remaining real-data/content acceptance.
