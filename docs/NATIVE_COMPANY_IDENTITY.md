# Register a company from separate native source words

Updated 4 November 2026. Native M1 parsing retains original words as separate
evidence records. A multiword company name therefore needs several records; it
cannot honestly be submitted as one exact quoted span. The new, explicitly
versioned `native-company-registration-1` profile preserves each original word
and its sealed parse. Existing legacy registrations retain their original shape.

The same administrator endpoint, `POST /v1/admin/entities`, accepts either
profile. Both use the existing append-only registry/identifier tables, current
administrator account, immutable review note, duplicate protection and unique
CIN binding. Registering a company does not accept a financial observation or
publish a corpus. The runtime candidate model has no registration authority.

## Activation and exact support

Use the current integration checkout and the installation's documented local
setup. Apply its migrations **through 23**, using the existing migration command
and selected local environment. Migration 23 adds guards and selects them only
for the new profile. Migrations 1–22, old registration bytes, original legacy
guard and accepted observations remain unchanged. Do not regenerate credentials
or copy another installation's private records/IDs.

The background worker copies application code into its image. Rebuild that
installation's approved worker image before submitting background processing
with the new registry/resolver configuration:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\compose.ps1 worker-build
```

Use matching API/worker checkouts and the documented worker lifecycle; mixed code
fingerprints cannot process the same job. The native source intake/financial
review commands remain explicit native-host paths. No dependency or worker
service is added by this source rebuild.

The initial native profile supports **COMPANY with one CIN**, no aliases or
additional identifiers. Its required support is a complete explicit heading of
one of these forms, in the original consecutive word order:

```text
<complete company name> CORPORATE IDENTITY NUMBER: <complete CIN>
<complete company name> CIN: <complete CIN>
```

These are inspection forms, not reconstructed source quotations. English
keywords permit ASCII case differences. Other names, labels, wording or missing
context require a supported future profile or a separately supported legacy
registration; do not drop words or alter evidence to make the pattern pass.

`legal_name_support` and `issuer_header` each contain:

- `schema_version: "native-entity-words-1"`;
- the actual `parse_version_id`;
- `spans`, each with its existing `evidence_id`, exact `start`, `end` and original
  `quote`. Every span must cover its complete native word, starting at zero.

The name must be the actual heading prefix. Its display label uses single spaces
between the separate words; this label is not an exact PDF quotation. The one
CIN's `ApprovedIdentifier.support` must be the heading's complete final word.
Both name/header supports must belong to that same sealed native parse/page,
retain consecutive unambiguous original indices and preserve every selected
word. A legacy paragraph, partial word, skipped/reordered word, foreign page or
another parse cannot substitute for this support.

Each phrase is limited to 128 words and 2,048 original text characters. Individual
anchors retain the existing 256-character limit; the company label is bounded at
256 characters. The registration requires a nonblank note of at most 2,000
characters. The backend and database independently verify source membership,
heading context, identifier validity and current administrator authority.

## Prepare an explicit reviewed request

Use the actual source packet/verified sealed parse. An existing numerical packet
retains the original `issuer_header` phrase, including separate word evidence,
page and native word references. Inspect it and the original source page before
choosing the name range and canonical company ID. Do not copy an uploaded label,
invent IDs, create a combined evidence record or treat page-wide co-occurrence as
name/CIN support. Check the existing registry/identifier binding before creating
a new company; existing identities are immutable and cannot be silently merged.

The Python contracts show the request shape without fabricated evidence values:

```python
from regintel.entities.models import (
    ApprovedIdentifier, NativeCompanyRegistration, NativeEntityWords,
)

# These variables must come from this installation's actual verified source and
# explicit administrator review, not fixtures or generated source quotations.
name_support = NativeEntityWords(
    schema_version="native-entity-words-1",
    parse_version_id=selected_parse_id,
    spans=reviewed_name_word_anchors,
)
heading = NativeEntityWords(
    schema_version="native-entity-words-1",
    parse_version_id=selected_parse_id,
    spans=reviewed_complete_heading_word_anchors,
)
request = NativeCompanyRegistration(
    schema_version="native-company-registration-1",
    id=reviewed_company_id,
    kind="COMPANY",
    legal_name=name_support.inspection_text(),
    legal_name_support=name_support,
    issuer_header=heading,
    aliases=(),
    identifiers=(ApprovedIdentifier(
        kind="CIN", value=heading.spans[-1].quote, support=heading.spans[-1],
    ),),
    review_note=actual_review_note,
)
```

Submit `request.model_dump(mode="json")` to the existing authenticated entity
endpoint with that installation's administrator account. Matching repeats return
the original registration. Changing its payload or reusing an already bound CIN
conflicts, with no partially created identity. The browser has no new identity
drafting form in this checkpoint; the API and repository are the explicit path.

## Reprocess current financial prerequisites

After a genuine identity decision, save/inspect the financial context against
the current registry, then run the existing bound gate with the actual sealed
parse. Keep any earlier unresolved record. Current resolver and numerical gate
fingerprints now include native identity inspection/source-order code; the
numerical fingerprint also includes migration 23. Old saved hashes are historical
identities, not values to edit or relabel as current.

A supported company identity can resolve `ISSUER`; it cannot resolve missing or
qualified units, periods, basis, policies or cross-page applicability. A gate
with unresolved mandatory checks remains review-required. Follow the independent
[numerical review/acceptance/publication workflow](NUMERICAL_ADMIN_WORKFLOW.md).
Published catalogs use the registration frozen with each accepted observation,
not today's global registry. M1 facts, M2 comparison, M3 context and M4 company
selection continue through that same published filing corpus version.

## Measured scope

See the [validation report](../data/native-company-identity-validation-report.json).
Authored blank-PDF/native-word fixtures exercise source gates, direct SQL,
current roles, conflicts, concurrency, immutable history, a populated-schema
upgrade and the four module APIs. Those are engineering checks, not actual
company approval or financial gold. The M4 consumer check retains the configured
`QUOTES_UNAVAILABLE` rejection; no price feed or priced runtime demo is enabled.

The worker check rebuilds the approved Dockerfile under an isolated local tag,
then checks current source/imports and parser inventory with networking disabled,
UID 10001, a read-only filesystem and dropped capabilities. Building may download
the existing locked dependencies; no host software or dependency versions are
changed. No worker service or live Celery/database delivery is started by that
import check.

The retained Premier and Waaree name/CIN heading wording matches this bounded
profile; no actual registration/review is performed by that wording inspection.
All four real numerical inputs and seven learning starter reviews remain
unresolved. Real amendment/module acceptance, feature/corpus freeze, held-out
evaluation and fresh-clone handoff remain necessary. No dependency, required
environment setting, additional service or public port is added.
