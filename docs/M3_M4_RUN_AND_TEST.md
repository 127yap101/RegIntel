# Run and test the learning and virtual-portfolio baseline

Updated 24 October 2026. These modules are on `codex/m2-comparison` in
127yap101/RegIntel. Pull that branch to work on M2–M4. The original `main` checkout
and its saved M1 test corpus have not been migrated or replaced.

## Another teammate's computer

Follow [the teammate setup guide](M1_TEAM_TESTING.md) for the pinned toolchain,
Docker Desktop, local environment files and accounts. For a new clone, select
the module branch explicitly:

```powershell
git clone --branch codex/m2-comparison https://github.com/127yap101/RegIntel C:\Projects\RegIntel
Set-Location C:\Projects\RegIntel
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

Use a new setup on that computer, or an existing compatible checkout and its
existing local configuration. Git does not contain passwords, accounts, database
volumes, original PDFs, embedding models or published filing data. Do not copy
another person's secret files into Git. Do not regenerate passwords against an
already populated Docker volume without following the existing setup guide.

After the documented local `.env` and `.env.auth` initialization, run these from
the new clone. These commands intentionally migrate **that clone's configured
database**, through migration 16. On Yash's current laptop, preserve the original
`D:\RegIntel` database and use the disposable checks below instead.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\compose.ps1 up
.\backend\.venv\Scripts\regintel-db.exe migrate --env-file .env
.\backend\.venv\Scripts\regintel-db.exe check --env-file .env
.\backend\.venv\Scripts\regintel-auth.exe seed --env-file .env --auth-env-file .env.auth
.\backend\.venv\Scripts\regintel-auth.exe check --env-file .env --auth-env-file .env.auth
.\backend\.venv\Scripts\regintel-api.exe --env-file .env --auth-env-file .env.auth
```

In another terminal in the same clone:

```powershell
pnpm --dir frontend dev
```

Open `http://127.0.0.1:5173`. Keep one API and one frontend process running per
port. If port 8000 is occupied, first identify the existing API; repeatedly
launching another instance does not fix it. The existing run guide documents
local account and service checks. macOS/Linux use the corresponding shell guide
and native executables; no new module dependency or mandatory env variable is added.

## M3: reviewed learning

1. Choose **Financial learning**, then sign in with that computer's seeded admin.
   An empty glossary is expected on a new database.
2. Enter a term, definition and actual source URL/title. Review the linked source
   yourself; the application retains the link and does not fetch or verify the
   source's educational correctness. Optionally enter an explicitly authored
   educational example. Inputs remain decimal strings and the backend calculates
   its result before review. Percentage change uses the left input as a positive
   baseline and the right input as the later value.
3. Save the draft and retain its displayed draft ID. Inspect the exact definition,
   source, optional metric link and calculated example. Add a review note and
   explicitly approve or reject. A rejected draft needs a new corrected draft;
   the existing decision cannot be edited.
4. Publish an approved definition. The glossary receives its own immutable version.
   Publication checks its parent version, so a stale administrator cannot silently
   discard somebody else's publication. **Refresh reviewed glossary** reloads the
   current parent while keeping the saved draft. **Load saved draft** restores its
   stored review as well, including an approval made before a browser restart.
5. Sign in as a learner. Approved published content and examples are readable;
   authoring controls are absent. Unreviewed drafts are not learner content.
6. For filing context, select a reviewed definition, a published company and a
   matching disclosure. A definition needs an explicitly reviewed link to an
   available M1 metric. **Show reviewed context** retains the exact published
   disclosure, corpus version and evidence; **View source page** uses M1's verified
   original-PDF viewer. No paraphrase or new filing fact is generated.

No financial glossary has been automatically seeded or marked human-reviewed.
The tests use labelled authored definitions; they do not establish educational
accuracy. A fresh empty M1 corpus has no company/disclosure choices. Existing
publication and evidence prerequisites remain mandatory.

## M4: virtual account and immutable outcomes

1. Choose **Virtual portfolio**, sign in and create the account. Its one-time
   opening virtual credit is **INR 100000.00**. Creating it again returns the same
   account; cash and holdings derive from immutable records.
2. Select a published company, buy/sell and a positive whole-share quantity. The
   server selects the quote; clients cannot supply prices or balances. This pilot
   currently uses whole shares and zero fees.
3. Quotes are unavailable by the user's explicit choice. Therefore a valid
   submitted order records `REJECTED / QUOTES_UNAVAILABLE`; cash and holdings do
   not move. No order can be placed against an unpublished/unknown company.
4. If the response is lost, **Retry same virtual order** resends the exact original
   request key and payload. The unconfirmed request alone is retained in this
   browser tab's session storage, scoped to its user; tokens and balances are not
   stored. After reload, sign in again and retry. A confirmed result clears the
   saved request. Closing the tab clears browser session storage; saved server
   history remains authoritative.
5. Refresh the portfolio and inspect its immutable history. Successful fixed-price
   buys, partial/final sells, insufficient cash, oversells and concurrent retries
   are tested through an explicitly labelled engineering provider in disposable
   tests. That provider is not configured in the runtime API. A reviewed dataset
   or provider is still needed for a successful interactive trade demonstration.

Market valuation/total value are explicitly unavailable. Returns, P&L, allocation
analytics and a reviewed quote-data workflow remain further M4 work. No real
money, recommendation, live execution or model-controlled balance change is added.

## Automated checks

The normal `scripts/run-checks.ps1` / `scripts/run-checks.sh` include the new
generated contracts, frontend tests and Chromium scenarios. Bootstrap and CI
generate ignored module schemas/types; do not hand-edit or commit generated files.

With the existing data services running and this clone's `.env` configured:

```powershell
.\backend\.venv\Scripts\python.exe scripts\check-migrations.py --test-file backend/tests/integration/test_learning_storage.py
.\backend\.venv\Scripts\python.exe scripts\check-migrations.py --test-file backend/tests/integration/test_portfolio_storage.py
pnpm --dir frontend exec playwright test tests/e2e/learning-portfolio.spec.ts --workers=1
```

Each database command creates and removes only its own `regintel_test_…` database
on the existing local PostgreSQL service. The browser scenarios use authored
responses and are separate from real HTTP/PostgreSQL checks. Configure
`REGINTEL_TEST_API_PORT` and `REGINTEL_TEST_WEB_PORT` when existing manual-test
servers occupy the default ports; verification here used 8012 and 5185 on loopback.
On this shared laptop, use the documented isolated-checkout Python path rather
than reinstalling the main editable environment.

See [the measured report](../data/learning-portfolio-validation-report.json) and
[current state](../CURRENT_STATE.md) for actual results and remaining acceptance.
M2 real numerical acceptance still needs mandatory validation, genuine review and
publication of the four bound numerical records; M3/M4 do not bypass those gates.
