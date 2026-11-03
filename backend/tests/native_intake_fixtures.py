"""Local plans over authored blank-PDF declarations, never genuine source approvals."""

import hashlib
from pathlib import Path

from backend.tests.native_context_fixtures import NativeCase, native_case
from regintel.ingestion.jobs import UploadMetadata
from regintel.parsing.configuration import canonical_configuration_bytes
from regintel.parsing.intake_models import IntakeFile, IntakePage, NativeIntakePlan


def reference(path: Path) -> IntakeFile:
    return IntakeFile(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def plan_for(case: NativeCase, directory: Path) -> NativeIntakePlan:
    baseline = directory / "intake-runtime.json"
    baseline.write_bytes(
        canonical_configuration_bytes(case.result.configuration.context_parser_configuration)
    )
    raw = directory / "intake-page-2.json"
    raw.write_bytes(case.result.captures[0].raw_bytes)
    return NativeIntakePlan(
        source=reference(case.source),
        parser_configuration=reference(baseline),
        native_manifest=reference(case.result.bank.directory / "manifest.json"),
        metadata=UploadMetadata(company_name_raw="Authored intake fixture", document_type="RHP"),
        context_pages=(IntakePage(pdf_page=2, raw_capture=reference(raw)),),
    )


def intake_case(directory: Path) -> tuple[NativeCase, NativeIntakePlan]:
    case = native_case(directory)
    return case, plan_for(case, directory)
