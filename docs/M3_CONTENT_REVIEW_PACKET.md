# M3 starter content: reviewer packet

Prepared 19 November 2026 for Shreya/the designated content reviewer. All seven
entries remain **DRAFT_UNREVIEWED**. This packet reproduces the current wording in
[the starter JSON](../data/learning-starter-drafts.json); it does not save a review
or publish a glossary. No reviewer identity or decision has been supplied.

## What to review

For each entry below, record **approve as written**, **request the specified
correction**, or **not ready**, with your name/date and a source-supported reason.
Check the definition, example, intended audience and applicable reporting
framework. Any changed wording needs its own saved draft and review. Keep M1
metric mappings empty unless you separately verify a specific registered metric.

The linked IFRS Foundation summaries were read again on 19 November. The source
alignment comments below are agent analysis, not human approval. These general
learning definitions do not establish which Indian accounting framework applies
to a filing, compliance with a standard, or the basis of a particular amount.
Current standards and their effective dates require separate applicability review.

## Exact proposed definitions

### 1. Statement of financial position

Key: `financial_position`

> A financial statement describing an entity's financial position at a specified date. Read its date separately from the periods covered by performance and cash-flow statements.

Source: [IAS 1 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/),
About: complete set of financial statements. The overview supports the date/period
distinction. No numerical example. Decision: **pending**.

### 2. Statement of profit or loss

Key: `profit_or_loss`

> A period-based statement of income and expenses recognised in profit or loss. Other comprehensive income is separately identified; a balance-sheet date alone does not describe this reporting period.

Source: [IAS 1 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/),
About: profit or loss and other comprehensive income. Check that the wording does
not imply two separate statements are mandatory. Decision: **pending**.

Exact hypothetical example: `SUBTRACT`, left `1200.00`, right `1000.00`, unit
`illustrative INR`. Expected arithmetic: `200.00`.

> Hypothetical arithmetic only: subtract 1000.00 of expenses from 1200.00 of income assumed to be recognised in profit or loss. This is not a complete financial statement or a filing claim.

### 3. Notes to financial statements

Key: `financial_statement_notes`

> Explanatory information accompanying the financial statements, including accounting policies. Notes supply context needed to interpret the amounts and presentations in the statements.

Source: [IAS 1 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/),
About: notes and explanatory information. Its history also records the material
accounting-policy-information amendment; avoid implying disclosure of every
policy is required. No numerical example. Decision: **pending**.

### 4. Comparative financial information

Key: `comparative_information`

> Amounts from a preceding reporting period presented alongside current-period information. Interpret each amount with its stated period and accompanying notes before comparing it.

Source: [IAS 1 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/),
About: annual statements and preceding-year comparative amounts. Decision:
**pending**.

Exact hypothetical example: `PERCENT_CHANGE`, left `100.00`, right `125.00`, unit
`illustrative units`. Expected arithmetic: `(125.00 - 100.00) / 100.00 * 100 = 25%`.
This is an authored exercise; the cited standard does not prescribe this formula.

> Hypothetical compatible amounts only: compare a positive baseline of 100.00 with a later amount of 125.00. The backend computes the percentage change; these are not company disclosures.

### 5. Statement of cash flows

Key: `cash_flow_statement`

> A statement explaining changes in cash and cash equivalents during a reporting period, grouped into operating, investing and financing activities. Non-cash transactions need separate interpretation.

Source: [IAS 7 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/),
About: cash-flow presentation and activity classifications. Wording to consider:
the final sentence could more explicitly state that non-cash investing/financing
transactions are excluded from the statement and disclosed separately. This is a
proposed clarification only; the starter has not been edited. Decision: **pending**.

Exact hypothetical example: `ADD`, left `50.00`, right `-20.00`, unit
`illustrative INR`. Expected arithmetic: `30.00`.

> Hypothetical cash-flow arithmetic only: add a cash inflow of 50.00 and a cash outflow represented by -20.00. No company, investment return or market price is represented.

### 6. Cash equivalents

Key: `cash_equivalents`

> Short-term, highly liquid investments readily convertible into a known cash amount with insignificant value-change risk. An investment is not a cash equivalent merely because it can be sold.

Source: [IAS 7 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/),
About: cash and cash-equivalent definitions. The draft retains all the listed
conditions; it does not classify any actual instrument. No numerical example.
Decision: **pending**.

### 7. Consolidated financial statements

Key: `consolidated_statements`

> Financial statements presenting a parent and its subsidiaries together as one economic entity. Preserve that reporting basis when comparing figures; do not silently substitute a parent's separate amounts.

Source: [IFRS 10 overview](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-10-consolidated-financial-statements/),
About: consolidated statements and the control principle. The overview supports
the group presentation concept. This short definition is not a control test and
does not describe all exemptions. No numerical example. Decision: **pending**.

## Recording the outcome

Use the administrator learning workspace described in
[the learning run guide](M3_M4_RUN_AND_TEST.md#m3-reviewed-learning). Loading a
starter only fills the form. Save the intended wording, inspect that saved
definition and example result, then record the actual supported review decision.
Publication is a separate action that selects reviewed saved definitions into an
immutable glossary version. Verify that a learner sees that exact version and
that changing versions clears the prior context selection.

No source URL, example result or checked box in this Markdown file grants
publication eligibility. The runtime review history is authoritative.
