# Shared published corpus across M1–M4

26 October 2026. Continue all four modules from tested source `4bad30a`, whose
Windows, Ubuntu and Linux infrastructure jobs pass in CI40341137291.

The filing explorer already pins M1 reads and M2 calculations to a selected
published corpus. Learning and portfolio independently fetch the latest head at
entry. If another publication occurs between workspace visits, one page session
can therefore switch filing inputs without an explicit corpus choice.

Keep a verified selected corpus in React memory across these workspaces. Pass
only its canonical identifier, never tokens, facts or account state. M1/M2 apply
the existing selected view; M3 filing context and M4 company/order inputs use the
active disclosures of that same corpus. Historical/as-of explorer filters remain
explicitly local to that explorer. Glossary, quote and portfolio versions stay
independent and visible through their existing contracts.

Resolve the initial head once through authenticated published reads. Promote a
selection only after the selected company page validates its corpus membership.
Do not fall back to a different head when a selected corpus is unavailable or a
response is mixed. Provide an explicit latest-publication action in the explorer;
an unavailable remembered selection can be cleared before another sign-in.
Sign-out clears the shared selection. Keep it out of browser storage and URLs.

Verify delayed/aborted reads, head changes, unavailable/mixed responses, navigation,
M2 request versions, M3 context and M4 committed order versions. Add a real
PostgreSQL/HTTP check over an authored published M1 corpus to exercise all four
consumer paths with independent glossary and portfolio versions. These are
engineering fixtures, not real filing approvals or research results.

Preserve original M1 endpoints/data, producer and publication gates, all eighteen
migrations, native/worker choices and quote unavailability. Add no dependency,
required setting or service. Real table acceptance/publication and actual learning
content review remain separate required work under the approved producer plan.
