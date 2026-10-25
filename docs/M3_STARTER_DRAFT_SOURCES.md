# Unreviewed learning starter pack

25 October 2026. Seven short educational drafts are provided in
`data/learning-starter-drafts.json`. They are agent-prepared paraphrases with
`DRAFT_UNREVIEWED` status, no human reviewer, no M1 metric mapping and no automatic
publication. They are not independently verified educational or legal content.

The primary summaries below were read on25October. The drafts retain their exact
URLs and the relevant About-section location:

| Primary source | Draft concepts |
|---|---|
| [IFRS Foundation: IAS 1 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/) | Statement of financial position; profit or loss; notes; comparative information |
| [IFRS Foundation: IAS 7 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/) | Cash-flow statement; cash equivalents |
| [IFRS Foundation: IFRS 10 overview](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-10-consolidated-financial-statements/) | Consolidated financial statements |

These are general IFRS learning references. They do not establish the applicable
Indian accounting framework, a filing's reporting basis or compliance. A reviewer
must check applicability, definition wording, examples and any proposed M1 metric
link before approving a saved draft. The summaries are not a substitute for the
full applicable standards. No original document or downloaded PDF is added to Git.

The three numerical examples are explicitly hypothetical:1200.00−1000.00,
percentage change from100.00 to125.00, and50.00+(−20.00). Expected arithmetic is
200.00,25% and30.00 respectively. The existing Decimal backend computes the result
after an explicit save; the starter pack supplies only inputs. These examples are
not company disclosures, market quotes or portfolio-return observations.

Administrators retrieve the pack through `GET /v1/learning/starter-pack`.
Anonymous users and learners cannot retrieve it. Loading a starter fills the
editing form, retains its source location and clears any previous metric/review
selection. It performs no definition, review or publication write. Save, inspect,
review and publish remain separate explicit actions. Published glossary history
continues to read its immutable saved records rather than this editable pack.

Other lookup attempts against a SEBI glossary PDF and an MCA PDF could not be
retrieved through the research tool; they are not used as verified pack sources.
No source fetch is required by the runtime loader, which reads only the bounded
project JSON. Network availability does not grant content approval.
