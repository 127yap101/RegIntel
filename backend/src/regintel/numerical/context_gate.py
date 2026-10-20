"""Deterministic joint-support inspection, before M1 evidence acceptance/publication."""

import hashlib
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

from regintel.contracts.models import ReportingBasis
from regintel.entities.models import canonical_bytes
from regintel.numerical.context_models import (
    CONTEXT_CODES,
    ContextCheck,
    ContextCode,
    NumericalContextInput,
    NumericalContextInspection,
    NumericalQuantityProposal,
    TableCellSupport,
    WordPhrase,
)
from regintel.numerical.context_periods import annual_period, normalized_words
from regintel.numerical.models import StoredNumericalPage
from regintel.numerical.source_pages import CellPreview
from regintel.validation.quantity import parse_decimal

State = Literal["PASS", "REVIEW", "FAIL"]
UNITS = {
    "million": "million",
    "millions": "million",
    "lakh": "lakh",
    "lakhs": "lakh",
    "crore": "crore",
    "crores": "crore",
    "billion": "billion",
    "billions": "billion",
}
UNIT_HEADER = re.compile(
    r"(?P<wrapped>\()?(?:in )?(?P<currency>INR|USD|₹|Rs\.) (?:in )?"
    r"(?P<unit>millions?|lakhs?|crores?|billions?)"
    r"(?:,? unless otherwise (?:specified|stated))?(?(wrapped)\))",
    re.I,
)
CURRENCY_DEFINITION = re.compile(
    r"all references to (?P<aliases>.+) are to "
    r"(?P<name>Indian Rupees|United States Dollars), the official currency of "
    r"(?P<country>the Republic of India|the United States of America)\.",
    re.I,
)
CAPTION = re.compile(
    r"(?:summary of (?:selected financial information derived from our|our company's) restated "
    r"(?:consolidated|standalone) financial information|restated summary profit and loss)\.?",
    re.I,
)
NON_ISSUER = re.compile(
    r"\b(?:third.party|industry|peer group|competitor|not our|not the company)\b", re.I
)
BASIS = re.compile(r"\b(consolidated|standalone)\b", re.I)


def context_configuration_sha256() -> str:
    package = Path(__file__).resolve().parents[1]
    paths = (
        "numerical/context_models.py",
        "numerical/context_periods.py",
        "numerical/context_gate.py",
        "numerical/context_repository.py",
        "numerical/models.py",
        "numerical/repository.py",
        "entities/models.py",
        "entities/repository.py",
        "candidates/repository.py",
        "ingestion/storage.py",
        "validation/models.py",
        "validation/quantity.py",
        "contracts/models.py",
        "contracts/primitives.py",
    )
    digest = hashlib.sha256()
    for name in paths:
        body = (package / name).read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def _text(phrase: WordPhrase) -> str:
    # A grammar input only, never a new exact source quote, block, span or rectangle.
    return normalized_words(" ".join(ref.quote for ref in phrase.words))


def _exact(phrase: WordPhrase, page: StoredNumericalPage) -> bool:
    words = page.capture.words
    return all(
        ref.word_index < len(words)
        and words[ref.word_index].orig == ref.quote
        and ref.end == len(ref.quote)
        and words[ref.word_index].from_ocr is False
        and words[ref.word_index].raw_rectangle is not None
        and words[ref.word_index].box is not None
        for ref in phrase.words
    )


def _cell(support: TableCellSupport, page: StoredNumericalPage) -> tuple[CellPreview | None, State]:
    capture = page.capture
    cell = next(
        (
            c
            for c in capture.cells
            if (c.table_index, c.cell_index) == (support.table_index, support.cell_index)
        ),
        None,
    )
    if cell is None:
        return None, "FAIL"
    mapping = next(
        m
        for m in capture.mappings
        if (m.table_index, m.cell_index) == (cell.table_index, cell.cell_index)
    )
    if mapping.state != "PROPOSED":
        return None, "REVIEW"
    if tuple(ref.word_index for ref in support.phrase.words) != mapping.word_indices:
        return None, "FAIL"
    return cell, "PASS"


def _local_context(phrase: WordPhrase, page: StoredNumericalPage, table: int, gap: float) -> bool:
    """Require an above-table caption/header with no closer intervening table preview."""
    boxes = [page.capture.words[ref.word_index].box for ref in phrase.words]
    assert all(box is not None for box in boxes)
    present = [box for box in boxes if box is not None]
    left, right = min(b.x0 for b in present), max(b.x1 for b in present)
    bottom = min(b.y0 for b in present)
    tables: dict[int, list[CellPreview]] = {}
    for cell in page.capture.cells:
        tables.setdefault(cell.table_index, []).append(cell)
    distances: dict[int, float] = {}
    for key, cells in tables.items():
        if any(c.box is None for c in cells):
            return False
        rects = [c.box for c in cells if c.box is not None]
        if not rects:
            continue
        top = max(b.y1 for b in rects)
        if bottom >= top and right > min(b.x0 for b in rects) and left < max(b.x1 for b in rects):
            distances[key] = bottom - top
    return (
        table in distances
        and distances[table] <= gap
        and all(distance > distances[table] for key, distance in distances.items() if key != table)
    )


def _issuer(input: NumericalContextInput, text: str) -> tuple[State, str]:
    match = re.fullmatch(r"(.+) (?:CORPORATE IDENTITY NUMBER|CIN): ([A-Z0-9]{21})", text, re.I)
    if match is None:
        return "REVIEW", "One complete issuer name and explicit CIN heading is required."
    name, cin = match[1], match[2]
    matches = [
        entity
        for entity in input.registry.entities
        if any(item.kind == "CIN" and item.value == cin for item in entity.identifiers)
    ]
    if len(matches) != 1:
        return "REVIEW", "The original CIN needs one unambiguous approved registry binding."
    entity = matches[0]
    if entity.id != input.draft.subject_entity_id or entity.kind != "COMPANY":
        return "FAIL", "The source issuer CIN does not identify the proposed subject."
    names = [entity.legal_name, *(alias.name for alias in entity.aliases)]
    if name.casefold() not in {normalized_words(value).casefold() for value in names}:
        return "FAIL", "The issuer heading does not match the identifier's approved name or alias."
    return "PASS", "One source issuer name/CIN matches the supplied approval snapshot."


def _currency(
    label: str, definitions: tuple[str, ...]
) -> tuple[Literal["INR", "USD"] | None, State, str]:
    direct: Literal["INR", "USD"] | None = (
        "INR" if label.upper() == "INR" else "USD" if label.upper() == "USD" else None
    )
    proposed: list[Literal["INR", "USD"]] = []
    for text in definitions:
        match = CURRENCY_DEFINITION.fullmatch(text)
        if match is None:
            return None, "REVIEW", "A supplied currency definition is unsupported or incomplete."
        alias_text = match["aliases"]
        aliases = re.findall(r'"([^"\n]+)"', alias_text)
        residue = re.sub(r'"[^"\n]+"', "", alias_text)
        if not aliases or re.fullmatch(r"[ ,]*(?:(?:or|and)[ ,]*)*", residue, re.I) is None:
            return None, "REVIEW", "Currency definitions require a bounded explicit alias list."
        currency: Literal["INR", "USD"] = (
            "INR" if match["name"].casefold() == "indian rupees" else "USD"
        )
        expected_country = (
            "the republic of india" if currency == "INR" else "the united states of america"
        )
        if match["country"].casefold() != expected_country:
            return None, "FAIL", "The explicit currency name and country conflict."
        if label.casefold() not in {alias.casefold() for alias in aliases}:
            return (
                None,
                "FAIL",
                "The local currency label is not defined by the supplied source clause.",
            )
        proposed.append(currency)
    if direct is not None:
        proposed.append(direct)
    if len(set(proposed)) > 1:
        return None, "FAIL", "Supplied currency definitions conflict; no currency is selected."
    if not proposed:
        return None, "REVIEW", "A currency symbol alone cannot establish an ISO currency."
    return proposed[0], "PASS", "The local label has explicit retained currency support."


def _check(code: ContextCode, state: State, message: str) -> ContextCheck:
    return ContextCheck(code=code, state=state, message=message)


def _metric_check(value: NumericalContextInput) -> ContextCheck:
    metric, policy = value.metric, value.policy
    if metric is None:
        return _check("METRIC", "REVIEW", "A registered metric and numerical policy are required.")
    if metric.id != value.draft.metric_id or metric.kind != "numeric_fact":
        return _check("METRIC", "FAIL", "The selected metric/policy identifiers or kind conflict.")
    if policy is None:
        return _check("METRIC", "REVIEW", "A registered metric and numerical policy are required.")
    if policy.metric_id != metric.id:
        return _check("METRIC", "FAIL", "The selected metric/policy identifiers or kind conflict.")
    if (
        policy.quantity_kind != "MONEY"
        or policy.period_kind != "DURATION"
        or not policy.required_reporting_basis
    ):
        return _check(
            "METRIC",
            "REVIEW",
            "Only monetary annual-flow policies with explicit basis are supported.",
        )
    row_text = re.sub(
        r"^(?:\([a-z]\)|[0-9]+\))\s*", "", _text(value.draft.row_label.phrase), flags=re.I
    )
    if row_text.casefold() not in {normalized_words(cue).casefold() for cue in metric.cue_phrases}:
        return _check(
            "METRIC", "FAIL", "The complete row label does not match a selected literal metric cue."
        )
    return _check(
        "METRIC", "PASS", "The complete row label and annual policy match the registered metric."
    )


def _value_check(phrase: WordPhrase) -> tuple[ContextCheck, Decimal | None]:
    if len(phrase.words) != 1 or len(phrase.words[0].quote) > 500:
        return _check(
            "VALUE", "FAIL", "One complete bounded original numeric word is required."
        ), None
    try:
        amount = parse_decimal(phrase.words[0].quote)
    except ValueError:
        return _check(
            "VALUE", "FAIL", "Dash, blank or malformed notation cannot become a number."
        ), None
    return _check(
        "VALUE", "PASS", "The original value has an exact unscaled Decimal interpretation."
    ), amount


def _unit_checks(
    value: NumericalContextInput,
) -> tuple[ContextCheck, ContextCheck, str | None, Literal["INR", "USD"] | None]:
    match = UNIT_HEADER.fullmatch(_text(value.draft.unit_header))
    if match is None:
        return (
            _check("UNIT", "REVIEW", "One explicit local monetary unit header is required."),
            _check("CURRENCY", "REVIEW", "The local header has no supported currency label."),
            None,
            None,
        )
    unit = UNITS[match["unit"].casefold()]
    policy = value.policy
    allowed = {UNITS.get(label, label) for label in policy.allowed_unit_labels} if policy else set()
    unit_check = _check(
        "UNIT",
        "PASS" if unit in allowed else "FAIL" if policy else "REVIEW",
        "Local source unit requires the matching registered metric policy.",
    )
    currency, state, message = _currency(
        match["currency"], tuple(_text(phrase) for phrase in value.draft.currency_definitions)
    )
    return unit_check, _check("CURRENCY", state, message), unit, currency


def _scope_check(value: NumericalContextInput, page: StoredNumericalPage) -> ContextCheck:
    scope = _text(value.draft.table_scope)
    if NON_ISSUER.search(scope):
        return _check("CONTEXT_SCOPE", "FAIL", "The caption identifies non-issuer source context.")
    if CAPTION.fullmatch(scope) is None:
        return _check(
            "CONTEXT_SCOPE", "REVIEW", "This caption needs issuer/statement applicability review."
        )
    if any(phrase.capture_id != page.id for phrase in value.draft.phrases()):
        return _check(
            "CONTEXT_SCOPE", "REVIEW", "Cross-page links require explicit applicability review."
        )
    return _check(
        "CONTEXT_SCOPE",
        "PASS",
        "Bounded local caption/header scope supports this preparation proposal.",
    )


def _basis_check(value: NumericalContextInput) -> tuple[ContextCheck, ReportingBasis]:
    draft = value.draft
    scope = _text(draft.table_scope)
    local = {match.upper() for match in BASIS.findall(scope)}
    supplied = (
        {match.upper() for match in BASIS.findall(_text(draft.basis_context))}
        if draft.basis_context
        else set()
    )
    basis: ReportingBasis = "UNKNOWN"
    if len(local) > 1 or len(supplied) > 1 or (local and supplied and local != supplied):
        return _check("BASIS", "FAIL", "Supplied and local reporting bases conflict."), basis
    if draft.basis_context is not None and draft.basis_context != draft.table_scope:
        context = _text(draft.basis_context).casefold()
        if (
            len(supplied) == 1
            and "our" in context
            and "restated" in context
            and ("financial information" in context or "summary statements" in context)
        ):
            basis = "CONSOLIDATED" if "CONSOLIDATED" in supplied else "STANDALONE"
        return _check(
            "BASIS", "REVIEW", "The separate basis clause needs statement applicability review."
        ), basis
    if len(local) == 1 and CAPTION.fullmatch(scope):
        basis = "CONSOLIDATED" if "CONSOLIDATED" in local else "STANDALONE"
        return _check(
            "BASIS", "PASS", "One local restated statement caption supplies the proposed basis."
        ), basis
    return _check(
        "BASIS", "REVIEW", "An applicable unambiguous reporting basis is required."
    ), basis


def _finish(
    value: NumericalContextInput,
    checks: dict[ContextCode, ContextCheck],
    quantity: NumericalQuantityProposal | None = None,
) -> NumericalContextInspection:
    draft = value.draft
    ordered = tuple(checks[code] for code in CONTEXT_CODES)
    status = (
        "QUARANTINED"
        if any(c.state == "FAIL" for c in ordered)
        else "REVIEW_REQUIRED"
        if any(c.state == "REVIEW" for c in ordered)
        else "SUPPORTED_PROPOSAL"
    )
    draft_sha = hashlib.sha256(canonical_bytes(draft)).hexdigest()
    source_sha = hashlib.sha256(canonical_bytes(value)).hexdigest()
    config_sha = context_configuration_sha256()
    identity = str(
        UUID(
            bytes=hashlib.sha256(
                (draft_sha + ":" + source_sha + ":" + config_sha).encode("ascii")
            ).digest()[:16],
            version=4,
        )
    )
    return NumericalContextInspection.model_validate(
        {
            "id": identity,
            "draft": draft,
            "draft_sha256": draft_sha,
            "source_input_sha256": source_sha,
            "configuration_sha256": config_sha,
            "state": status,
            "checks": ordered,
            "quantity": None if status == "QUARANTINED" else quantity,
        }
    )


def _source_check(
    value: NumericalContextInput, pages: dict[str, StoredNumericalPage]
) -> ContextCheck:
    draft = value.draft
    if (
        set(pages) != set(draft.capture_ids)
        or len({p.source_blob_id for p in value.pages}) != 1
        or len({p.capture.page_index for p in value.pages}) != len(value.pages)
        or any(
            p.filing_version_id != draft.filing_version_id
            or p.capture.sdk_configuration_sha256 != value.sdk_configuration_sha256
            or p.capture.preparation_code_sha256 != value.preparation_code_sha256
            for p in value.pages
        )
        or len({p.capture.source_sha256 for p in value.pages}) != 1
    ):
        return _check(
            "SOURCE",
            "FAIL",
            "Context must retain one source/version and the selected preparation/configuration.",
        )
    return _check(
        "SOURCE",
        "PASS",
        "Retained source/version and selected preparation/configuration membership agree.",
    )


def _table_check(value: NumericalContextInput, page: StoredNumericalPage) -> ContextCheck:
    draft = value.draft
    selected = (draft.value, draft.row_label, draft.period_header)
    if any(
        s.phrase.capture_id != page.id or s.table_index != draft.value.table_index for s in selected
    ):
        return _check(
            "TABLE", "FAIL", "Value, row and period column must belong to one captured table."
        )
    cells = tuple(_cell(s, page) for s in selected)
    if any(state != "PASS" for _, state in cells):
        state: State = "FAIL" if any(state == "FAIL" for _, state in cells) else "REVIEW"
        return _check(
            "TABLE",
            state,
            "Cell references must retain the complete unambiguous native-word mapping.",
        )
    cell, row, column = (item[0] for item in cells)
    assert cell is not None and row is not None and column is not None
    if (
        row.cell_index == cell.cell_index
        or column.cell_index == cell.cell_index
        or not row.row_index <= cell.row_index < row.row_index + row.row_span
        or row.column_index + row.column_span > cell.column_index
        or not column.column_index <= cell.column_index < column.column_index + column.column_span
        or column.row_index + column.row_span > cell.row_index
    ):
        return _check(
            "TABLE", "FAIL", "The selected row or period header does not align with the value cell."
        )
    if (
        not row.row_header
        or not column.column_header
        or cell.row_header
        or cell.column_header
        or (cell.row_span, cell.column_span) != (1, 1)
    ):
        return _check(
            "TABLE", "REVIEW", "This grid needs explicit row/header or merged-cell review."
        )
    overlapping = [
        c
        for c in page.capture.cells
        if c.table_index == cell.table_index
        and c.row_index <= cell.row_index < c.row_index + c.row_span
        and c.column_index <= cell.column_index < c.column_index + c.column_span
    ]
    if len(overlapping) != 1:
        return _check(
            "TABLE", "REVIEW", "Multiple preview cells cover the proposed value location."
        )
    return _check(
        "TABLE",
        "PASS",
        "Original word mappings retain one aligned value, row label and period column.",
    )


def _local_check(value: NumericalContextInput, page: StoredNumericalPage) -> ContextCheck | None:
    draft = value.draft
    if draft.table_scope.capture_id != page.id or draft.unit_header.capture_id != page.id:
        return _check(
            "CONTEXT_SCOPE",
            "FAIL",
            "Local table caption and unit header cannot be borrowed from another page.",
        )
    if not _local_context(
        draft.unit_header, page, draft.value.table_index, 96.0
    ) or not _local_context(draft.table_scope, page, draft.value.table_index, 160.0):
        return _check(
            "CONTEXT_SCOPE",
            "REVIEW",
            "The caption/unit header needs bounded same-table geometry review.",
        )

    return None


def inspect_context(value: NumericalContextInput) -> NumericalContextInspection:
    """Inspect one proposal; models cannot accept, publish or bypass mandatory M1 gates."""
    value = NumericalContextInput.model_validate(value.model_dump(mode="python"))
    draft = value.draft
    pages = {page.id: page for page in value.pages}
    checks = {
        code: ContextCheck(code=code, state="REVIEW", message="This context remains unresolved.")
        for code in CONTEXT_CODES
    }

    def check(code: ContextCode, state: State, message: str) -> None:
        checks[code] = ContextCheck(code=code, state=state, message=message)

    checks["SOURCE"] = _source_check(value, pages)
    if checks["SOURCE"].state != "PASS":
        return _finish(value, checks)
    if any(not _exact(phrase, pages[phrase.capture_id]) for phrase in draft.phrases()):
        check(
            "EXACT_WORDS",
            "FAIL",
            "A reference lacks an exact complete native word and original geometry.",
        )
        return _finish(value, checks)
    check(
        "EXACT_WORDS",
        "PASS",
        "Every supplied reference retains its exact native word and word envelope.",
    )
    page = pages[draft.value.phrase.capture_id]
    checks["TABLE"] = _table_check(value, page)
    if checks["TABLE"].state != "PASS":
        return _finish(value, checks)
    local = _local_check(value, page)
    if local is not None:
        checks["CONTEXT_SCOPE"] = local
        return _finish(value, checks)

    issuer_state, issuer_message = _issuer(value, _text(draft.issuer_header))
    check("ISSUER", issuer_state, issuer_message)
    checks["METRIC"] = _metric_check(value)
    checks["VALUE"], amount = _value_check(draft.value.phrase)
    checks["UNIT"], checks["CURRENCY"], unit, currency = _unit_checks(value)
    period, period_state, period_message = annual_period(
        _text(draft.period_header.phrase),
        tuple(_text(phrase) for phrase in draft.fiscal_definitions),
    )
    check("PERIOD", period_state, period_message)
    checks["CONTEXT_SCOPE"] = _scope_check(value, page)
    checks["BASIS"], basis = _basis_check(value)
    quantity = (
        None
        if amount is None
        else NumericalQuantityProposal(
            raw_value=draft.value.phrase.words[0].quote,
            normalized_value=amount,
            normalized_unit=unit,
            currency=currency,
            period=period,
            basis=basis,
        )
    )
    return _finish(value, checks, quantity)
