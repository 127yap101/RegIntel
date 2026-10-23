# M3 and M4 implementation during remaining M2 work

On23October2026 the user explicitly requested starting the remaining M2, M3 and
M4 modules because time is short. This authorizes implementation of these modules
through the existing published M1 contracts while preserving its interfaces and
existing data. It does not waive evidence, review, publication or financial gates.
The finalized module definitions and build document remain unchanged; no invented
numbered subphases are introduced.

## M3 first usable slice

Implement an administrator-authored glossary draft, immutable review decision and
independently versioned publication in PostgreSQL. Authenticated learners read
only approved definitions and approved examples from an explicitly selected
learning version. Preserve source links and distinguish educational examples
from filing facts. Contextual filing explanations consume published M1 IDs and
evidence through its existing read service, retaining the selected corpus version.

Optional paraphrase remains disabled. No model creates definitions, examples,
citations, approvals or financial results. An empty reviewed glossary is explicit,
not filled with invented approvals. Verify definition/version/source membership,
context selection, deterministic numerical examples and access/review failures.

## M4 first usable slice

Implement per-user virtual accounts, server-controlled quote-snapshot inputs,
strict Decimal order evaluation, atomic immutable outcomes and ledger replay in
PostgreSQL. Idempotency keys bind the complete order payload; conflicting reuse
fails and concurrent duplicate submissions commit one outcome. Cash and holdings
derive from the ledger. Reject insufficient cash, oversells and stale/missing
prices; expose missing valuation inputs explicitly.

Keep M2's quote endpoint unavailable as requested. No runtime price is invented or
accepted from a client. Fixed-price acceptance fixtures exercise successful buys,
partial/final sells and replay through a supplied test provider; those prices are
labelled engineering data and are not a market dataset. Provider configuration
and independent portfolio/quote versions remain explicit. No real-money execution,
recommendation, price prediction or model-controlled order path is added.

## Delivery and verification

Use the existing backend/frontend stack, local authentication, private data
services and portable check runners. Add module-owned migrations only; freeze
existing migrations. Use owned disposable databases for live checks and preserve
the primary corpus. Push tested implementation checkpoints to the authorized
branch so teammates can continue and test. Record actual checks and remaining
acceptance gaps in CURRENT_STATE.md rather than claiming all modules complete.
