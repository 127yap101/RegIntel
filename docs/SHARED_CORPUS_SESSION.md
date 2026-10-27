# One published filing corpus across M1–M4

The filing explorer, comparison, financial learning and virtual portfolio now
retain one verified filing-corpus selection for the current page session. This
implements the version-consistency part of integration I.2; it does not declare
the feature/corpus freeze or the four modules complete.

## Use and check

Use branch `codex/m2-comparison` and the existing
[run guide](M3_M4_RUN_AND_TEST.md). Sign in to the published filing explorer.
Its displayed **Viewing corpus** identifies the selected publication. Comparison
uses that corpus. After signing in to learning or portfolio, **Selected filing
corpus** identifies the same publication, even if another publication has become
the latest head in the meantime. Authentication remains local to each workspace;
the shared state contains only the corpus identifier.

M1/M2 history and date filters apply to the explorer. M3 company context and M4
company/order inputs use active disclosures at the selected corpus. Glossary,
quote-snapshot and portfolio versions remain independent. A filing-corpus choice
does not grant access to another user's portfolio or administrator review APIs.

Use **Use latest published corpus** in the explorer to explicitly verify and
select the latest publication. This clears the previous company selection,
comparison, answer and source view. Applying a published corpus ID through the
existing explorer form also updates the shared selection after verification.
If a remembered corpus is unavailable, return to the explorer sign-in form and
choose **Use latest corpus at next sign-in**, then sign in again.

An unavailable selected corpus or a response from a different corpus cannot
silently select a newer publication. Learning definitions and the virtual account
remain usable independently; company context and new orders require verified
published company inputs. Sign-out clears the selection. Reloading the page also
resolves it afresh. The selection and credentials are not stored in browser
storage or URLs.

An order whose response was lost retains its original request key and filing
corpus under the existing per-user, per-tab retry mechanism. If a later page
session selects a different corpus, the portfolio explains this difference.
**Retry same virtual order** preserves the original inputs. It cannot rewrite an
already committed order to the newly selected corpus.

## Verification and limits

The dedicated hook tests cover initial selection, delayed/aborted responses,
mixed versions and unavailable selections. Browser scenarios exercise navigation
across all four modules, explicit latest selection, failures, sign-out and an
order retry after reload. An owned PostgreSQL/HTTP integration fixture exercises
real application publication, comparison, learning and ledger boundaries with
authored source data, including permissions and unavailable publications.
See [the measured report](../data/shared-corpus-validation-report.json) for the
actual completed checks. Authored fixtures are not real filing approvals, market
prices, research gold or measured extraction effectiveness.

No dependency, migration, required environment variable, service or public API
contract is added. Original M1 data and endpoints are preserved. Real numerical
acceptance/publication still needs its versioned adapter and mandatory evidence
gates. The four retained real numerical gates remain unresolved; the seven M3
starter definitions still need actual review. Quotes remain unavailable by the
user's decision, so ordinary virtual orders record that rejection without moving
cash or holdings. Held-out research evaluation and fresh-clone handoff remain
required work.
