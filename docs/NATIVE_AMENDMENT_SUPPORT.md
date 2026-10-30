# Amendment evidence from separate original words

This extends the existing M1 publication workflow with
`native-amendment-words-1`. A support retains its selected parse ID and an ordered
list of separate whole original-word spans. Single original-block spans remain
readable and usable. The new form applies to parent/child issuer identities,
the child's parent reference, effect statements and effective-date support.

No combined quotation, synthetic evidence record, new filing identity or financial
value is created. Each word retains its existing evidence ID, exact Unicode
offsets and original text. The sealed parse supplies its original word position,
source page and geometry. Joined text is internal to deterministic semantic
inspection; the UI displays separate original spans.

## Source and context gates

The server verifies every support against the complete sealed M1 artifact and
its projection. Ordered-word support requires the verified `regintel-native-context`
adapter/configuration (1.1). Legacy Docling text cells can contain whole paragraphs;
their source-ref shape alone does not identify native words. Existing single-block
supports retain their exact spans and bounded sentence-context checks.
Native support requires one filing, parse and page, distinct complete words,
and consecutive original native indices. Request order is a proposal, not proof.
The client cannot supply trusted indices. Missing/unavailable intervening words,
partial original projections, OCR substitutions, duplicate positions, changed
source membership and reordered words are rejected.

Native effect support must include a bounded complete statement. The first word
must start the page's native sequence or follow a supported sentence boundary;
the final word must retain its sentence-ending punctuation. Known abbreviations
do not independently establish a boundary. An isolated native cue cannot bypass
this check through the legacy single-span shape. Negated, proposed and conditional
operations—including `not`, `may`, `expected`, `if`, `unless` and `subject to`—
remain unsupported. A review note does not override a mandatory failure.

An effective date needs exact original support within its effect statement.
Native date words must be a contiguous subsequence of that statement; a single
date span must remain within one of its exact words/blocks. Conventional explicit
English/ISO date forms are checked deterministically, including an original
terminal full stop. Publication dates are not inferred to be effective dates.
Missing/unsupported dates remain unavailable for as-of answers.

The pilot bounds one native support to 128 words and 20,000 original characters.
This conservative sentence/operation/date policy is not a general language
understanding or transcription-accuracy claim. Ambiguous layouts, cross-page
phrases, unknown boundaries or broader wording require further supported work.

## Administrator workflow

Use [numerical review](NUMERICAL_ADMIN_WORKFLOW.md) to obtain an actually accepted
candidate. Its context/candidate/acceptance decisions remain separate from the
lineage/effect decision and final corpus publication.

1. Select the actual current published parent in **Prepare a publication**, then
   add the accepted child candidate. Both source versions must have sealed parses.
2. Choose **Record an evidence-backed amendment effect**. Enter the actual parent
   and child filing versions, approved issuer and relationship. The declared
   parent, where present, must match the reviewed lineage.
3. For a native identity/reference/statement/date field, choose **Use ordered
   original words**. Enter the existing evidence IDs in their actual source order
   and select **Load original words**. Source intake supplies those IDs; a fresh
   clone does not contain another installation's private sources or IDs.
4. Inspect the separate loaded words. Source buttons open the verified original
   PDF page. A failed reload clears earlier loaded support. Controls stay locked
   while the read is pending; sign-out cancels it and clears private state.
5. Select the explicit operation and exact affected observation/new candidate
   IDs. Retain the whole effect statement. Supply the effective date and its
   exact support only when justified. Add the actual review explanation.
6. **Check and create publication draft**, inspect its source/decision scope, then
   separately **Publish this approved build**. Publication freshly verifies source,
   context, approvals and order at both build and final commit.

Correction/supersession removes only explicitly named active parent observations
from the active view. Historical observations and earlier corpus versions retain
their original bytes and source links. Addition/supplementation/removal retain
their existing scoped semantics. A later document never replaces all earlier
facts automatically. M2 comparisons, M3 context and M4 company selection continue
to consume the same explicitly selected published corpus.

## Manual module acceptance after real source review

Use an actual reviewed parent/child pair and record both published corpus IDs.
The authored test fixture cannot supply the required source/content decisions.

| Module | Check | Expected behavior |
| --- | --- | --- |
| M1 | Select the parent corpus, then the corrected corpus in the filing explorer. Inspect current, historical and supported as-of views. | Only the explicitly affected observation changes active status. Both original sources remain inspectable; an unsupported effect date gives temporal unavailability. |
| M2 | Compare the corrected company against an actually compatible peer, keeping the selected corpus explicit. Open each calculation input. | The current result uses the corrected accepted input and exact source evidence. Missing period/unit/basis compatibility blocks arithmetic. |
| M3 | Select a reviewed glossary version and open filing context from the corrected corpus; inspect the earlier corpus separately. | Current context uses the active corrected observation. Earlier source context remains available only through its explicit historical/corpus selection. |
| M4 | Select the same published filing corpus in the virtual portfolio workspace. Inspect existing committed orders and ledger history. | Company selection follows the chosen corpus. Earlier committed ledger outcomes retain their snapshots; unavailable runtime quotes prevent a newly priced order. |

Record real inputs, selected versions, observed results and failures. Successful
authored tests or a rendered dashboard do not complete this real acceptance.

## Storage, verification and limitations

Migration 22 adds/replaces only publication-support inspection functions and the
relevant amendment dispatch. Migrations 1–21 remain unchanged. The general
candidate-span contract, original publication trigger and unrelated build/history /
acceptance/authority checks remain intact; a regression compares the retained
build guard byte-for-byte apart from its amendment-support calls. Source order
and context are also checked independently in PostgreSQL. No dependency, required
environment variable, provider, quote feed or public port is added.

This checkpoint does not migrate the original laptop database. Fresh/updated
installations follow [team setup](M1_TEAM_TESTING.md) and apply the checked-in
migrations to their intended local database. To verify without changing the main
database, use the existing owned-database helper from this checkout:

```powershell
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py --test-file backend/tests/integration/test_native_amendment_storage.py
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py --test-file backend/tests/integration/test_native_numerical_amendments.py
```

The helper removes only its own disposable database. The
[measured report](../data/native-amendment-validation-report.json) records actual
counts, source hashes, cleanup and earlier attempts. The frozen browser fixture
comes from owned PostgreSQL/HTTP correction scenarios using authored blank PDFs
and declared word geometry. It does not establish real filing accuracy, genuine
content approval or research effectiveness.

The four real numerical inputs and seven M3 starter drafts still need their
actual source/content resolution and review. Real amendment-pair acceptance,
held-out evaluation, corpus/feature freeze and fresh-clone handoff remain required.
Runtime quotes remain unavailable by user choice.

Continue with the [team acceptance checklist](TEAM_ACCEPTANCE_CHECKLIST.md),
the real [M2 acceptance plan](../data/analysis-acceptance-plan.json) and the
unreviewed [M3 starter drafts](../data/learning-starter-drafts.json). Populate
acceptance inputs from the actually reviewed published corpus and independent
expectations; authored correction values or IDs cannot fill those records.
