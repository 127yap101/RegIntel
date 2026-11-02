# Find and open stored numerical checks

2 November 2026. The current `codex/m2-comparison` administrator workspace can
discover saved numerical gates without requiring a copied gate ID. This is a
private read-only view of retained inspections and recorded context decisions.
It does not create an inspection, approve a context, accept a fact or publish.

## Use the queue

1. Follow [the numerical administrator setup](NUMERICAL_ADMIN_WORKFLOW.md),
   including that installation's existing numerical runtime descriptor and data
   services. Sign in as a current administrator and choose **Numerical filings**.
2. In **Find stored numerical checks**, optionally enter part of the **Uploaded
   company name**. Search is a case-insensitive literal substring of intake
   metadata. `%` and `_` are ordinary characters. This label is not an accepted
   company identity, alias match or financial fact.
3. Choose a **Stored numerical check status** and **Recorded numerical context
   review**, then select **Find numerical checks**. The default finds unreviewed
   stored checks across all gate states. Rows retain the document type, stored
   gate and review states, optional proposed raw value/period end, gate ID and
   filing version. Proposals remain unaccepted, including those marked ready.
4. Select **Open stored check**. The browser loads the existing complete review
   packet and verifies that its immutable gate and filing source match the row.
   An already recorded review must also match; it cannot disappear or be replaced.
   Inspect the original words and source pages, then follow the separate context,
   candidate, acceptance and publication steps in the
   [review workflow](NUMERICAL_ADMIN_WORKFLOW.md#review-accept-and-publish).
5. Use **Refresh numerical checks** after recording a decision or when another
   administrator has worked on the data. The list is a page read at one moment;
   the loaded packet may show a later recorded review. Changing filters or pages
   clears the previous packet, source view and unsubmitted notes. New selections
   reset decision inputs to **Reject** until the reviewer chooses otherwise.

Direct **Saved numerical gate ID** lookup remains available. To resume a stored
candidate and its decision, enter its actual candidate ID in the existing optional
field and load the review. The queue does not guess a candidate or select the
latest timestamp as authority.

Queue navigation and filters are disabled while a context, candidate or
acceptance write has an uncertain outcome. Retry the exact retained write first.
Logout/revocation clears private results and aborts reads; a late response cannot
restore the queue. The queue writes no browser storage.

## Bounds and unavailable data

`GET /v1/admin/numerical/gates` accepts `state`, `review`, `query`, `offset` and
`limit`. Queries are valid Unicode, at most 120 characters and contain no null
character. Offset is 0–10,000; limit is 1–20. Stable gate-ID ordering and an
explicit `has_more` support pagination. Narrow the filters at the offset bound.
The private response has `scope=RETAINED_HISTORY_ONLY` and no published version
in its envelope metadata. It cannot stand in for a published M1 contract.

The reader verifies canonical result/review/request bytes, hashes, source/parse/
context membership and review audit metadata. It fetches bounded retained results,
not a complete gate input of up to 40 MiB for every row. An 8 MiB retained-payload
budget fails explicitly rather than returning a partial queue page.
It performs no review, acceptance, publication or source-file write.

An empty verified page means no records match that page and those filters.
Unavailable storage/configuration, invalid history or a payload-budget failure
produces an error, not an empty success. A fresh clone has no other laptop's gate
records or original PDFs; source intake and gate creation must happen first.

Stored `READY_FOR_REVIEW` does not establish current eligibility. Current source,
registry, policy or configuration may have changed. Existing review, candidate,
acceptance and publication actions still recheck their mandatory prerequisites.
The original gate/review files and all 22 migration bytes are unchanged by this
feature; its models and reader are separate from their frozen fingerprints.

See [the measured report](../data/numerical-review-queue-validation-report.json)
for actual checks, capture provenance and limits. The captured hostile intake
label, authored blank PDF/geometry and duplicate test registry entries are
engineering fixtures. They are not real source review, annotations or research
performance. All four real numerical inputs and seven learning starters still
need their actual supported review/acceptance work.
