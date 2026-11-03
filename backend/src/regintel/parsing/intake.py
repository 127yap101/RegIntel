"""Replay explicit offline captures, then persist through the existing M1 producer.

No parser SDK, model execution, financial decision or publication is performed.
The check path uses temporary in-memory identities that never enter storage.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from regintel.auth.types import User
from regintel.evidence.projection import MAX_ARTIFACT_BYTES, MAX_CONFIGURATION_BYTES
from regintel.ingestion.repository import JobRepository
from regintel.numerical.models import StoredNumericalPage, page_capture_id
from regintel.numerical.repository import (
    NumericalRepository,
    NumericalSourceError,
    _authorize,
    _checked,
    _json_bytes,
    _unique_object,
)
from regintel.numerical.source_pages import (
    MAX_CAPTURE_BYTES,
    NumericalPageCapture,
    build_page_capture,
    capture_bytes,
)
from regintel.parsing.configuration import (
    MAX_DESCRIPTOR_BYTES,
    ParserRuntimeConfiguration,
    _read_regular_file,
)
from regintel.parsing.intake_models import (
    IntakeFile,
    NativeIntakeCheck,
    NativeIntakePlan,
    NativeIntakeResult,
)
from regintel.parsing.models import artifact_sha256, canonical_artifact_bytes
from regintel.parsing.native_context import (
    ContextCapture,
    NativeContextParse,
    build_native_context_parse,
    project_native_context,
)
from regintel.parsing.native_repository import NativeM1Producer
from regintel.parsing.native_source import (
    MAX_MANIFEST_BYTES,
    MAX_PAGE_BYTES,
    MAX_SOURCE_BYTES,
    NativeSourceBank,
    canonical_bytes,
    read_native_source,
)

MAX_PLAN_BYTES = 256 * 1024
MAX_CONTEXT_BYTES = 128 * 1024 * 1024


def _json(body: bytes) -> object:
    return json.loads(body, object_pairs_hook=_unique_object)


def load_intake_plan(path: Path) -> NativeIntakePlan:
    return NativeIntakePlan.model_validate(_json(_read_regular_file(path, MAX_PLAN_BYTES)))


def _read(selected: IntakeFile, maximum: int) -> bytes:
    body = _read_regular_file(Path(selected.path), maximum)
    if hashlib.sha256(body).hexdigest() != selected.sha256:
        raise ValueError("Selected intake bytes differ from their explicit fingerprint.")
    return body


@dataclass(frozen=True)
class PreparedPage:
    raw_bytes: bytes
    capture: NumericalPageCapture


@dataclass(frozen=True)
class PreparedIntake:
    plan: NativeIntakePlan
    source_bytes: bytes
    baseline: ParserRuntimeConfiguration
    bank: NativeSourceBank
    pages: tuple[PreparedPage, ...]
    check: NativeIntakeCheck


def _temporary_captures(pages: tuple[PreparedPage, ...]) -> tuple[ContextCapture, ...]:
    version, blob, actor = str(uuid4()), str(uuid4()), uuid4()
    result = []
    for page in pages:
        digest = hashlib.sha256(capture_bytes(page.capture)).hexdigest()
        result.append(
            ContextCapture(
                StoredNumericalPage(
                    id=page_capture_id(version, blob, digest),
                    filing_version_id=version,
                    source_blob_id=blob,
                    prepared_sha256=digest,
                    submitted_by=actor,
                    auth_version=1,
                    capture=page.capture,
                ),
                page.raw_bytes,
            )
        )
    return tuple(result)


def prepare_intake(plan: NativeIntakePlan) -> PreparedIntake:
    """Read/check all explicit sources and the complete evidence bridge without writes."""
    source = Path(plan.source.path)
    source_bytes = _read(plan.source, MAX_SOURCE_BYTES)
    baseline = ParserRuntimeConfiguration.model_validate(
        _json(_read(plan.parser_configuration, MAX_DESCRIPTOR_BYTES))
    )
    if len(source_bytes) > baseline.source_limits.max_file_bytes:
        raise ValueError("The source exceeds the selected parser's byte limit.")
    manifest = Path(plan.native_manifest.path)
    if manifest.name != "manifest.json":
        raise ValueError("Select the existing complete bank manifest.json.")
    _read(plan.native_manifest, MAX_MANIFEST_BYTES)
    bank = read_native_source(source, manifest)
    if (
        bank.manifest.source_sha256 != plan.source.sha256
        or bank.manifest.source_page_count > baseline.source_limits.max_pages
    ):
        raise ValueError("The native bank differs from this bounded selected source.")
    pages = []
    total = 0
    for selected in plan.context_pages:
        # Apply the aggregate limit before reading each file, not after allocating it.
        body = _read(selected.raw_capture, min(MAX_CAPTURE_BYTES, MAX_CONTEXT_BYTES - total))
        total += len(body)
        raw = _json_bytes(_json(body))
        total += max(0, len(raw) - len(body))
        if total > MAX_CONTEXT_BYTES:
            raise ValueError("Selected page captures exceed their aggregate byte bound.")
        capture = build_page_capture(
            _json(raw),
            source=source,
            pdf_page=selected.pdf_page,
            expected_source_sha256=plan.source.sha256,
            expected_sdk_configuration_sha256=baseline.sdk_configuration_sha256,
        )
        pages.append(PreparedPage(raw, capture))
    complete = tuple(pages)
    temporary = _temporary_captures(complete)
    result = build_native_context_parse(
        bank,
        source=source,
        baseline=baseline,
        captures=temporary,
        parse_id=str(uuid4()),
        filing_id=str(uuid4()),
        filing_version_id=temporary[0].stored.filing_version_id,
        source_blob_id=temporary[0].stored.source_blob_id,
    )
    project_native_context(result.artifact, result.configuration)
    # Catch a changed manifest/original before returning a successful preparation receipt.
    if _read(plan.source, MAX_SOURCE_BYTES) != source_bytes:
        raise ValueError("The original source changed during intake preparation.")
    _read(plan.native_manifest, MAX_MANIFEST_BYTES)
    check = NativeIntakeCheck(
        source_sha256=plan.source.sha256,
        source_pages=bank.manifest.source_page_count,
        native_manifest_sha256=bank.manifest.sha256,
        processing_configuration_sha256=result.configuration.processing_configuration_sha256,
        evidence_pdf_pages=tuple(page.pdf_page for page in plan.context_pages),
        prepared_sha256=tuple(c.stored.prepared_sha256 for c in temporary),
    )
    return PreparedIntake(plan, source_bytes, baseline, bank, complete, check)


def _verify_sealed(
    source: NumericalRepository, result: NativeContextParse, job_id: str, user: User
) -> None:
    projection = project_native_context(result.artifact, result.configuration)
    with source.connect() as connection, connection.transaction():
        _authorize(connection, user)
        stored = connection.execute(
            "SELECT artifact_bytes,configuration_bytes,format_version "
            "FROM regintel.parse_artifacts "
            "WHERE job_id=%s AND parse_version_id=%s",
            (UUID(job_id), UUID(result.artifact.id)),
        ).fetchone()
        manifest = connection.execute(
            "SELECT manifest_bytes FROM regintel.native_parse_manifests WHERE parse_version_id=%s",
            (UUID(result.artifact.id),),
        ).fetchone()
        captures = connection.execute(
            "SELECT capture_id FROM regintel.native_parse_context_captures "
            "WHERE parse_version_id=%s ORDER BY page_index",
            (UUID(result.artifact.id),),
        ).fetchall()
        retained_pages = connection.execute(
            "SELECT count(*) FROM regintel.native_parse_source_pages WHERE parse_version_id=%s",
            (UUID(result.artifact.id),),
        ).fetchone()
        if retained_pages != (result.bank.manifest.source_page_count,):
            raise NumericalSourceError("The retained native source coverage is incomplete.")
        for page, receipt in zip(result.bank.pages(), result.bank.manifest.pages, strict=True):
            retained = connection.execute(
                "SELECT page_bytes,page_sha256,word_count "
                "FROM regintel.native_parse_source_pages "
                "WHERE parse_version_id=%s AND page_index=%s",
                (UUID(result.artifact.id), page.page_index),
            ).fetchone()
            if (
                retained is None
                or retained[1:] != (receipt.sha256, receipt.word_count)
                or _checked(retained[0], receipt.sha256, MAX_PAGE_BYTES) != canonical_bytes(page)
            ):
                raise NumericalSourceError("Retained native page bytes differ from this intake.")
    if (
        stored is None
        or _checked(stored[0], artifact_sha256(result.artifact), MAX_ARTIFACT_BYTES)
        != canonical_artifact_bytes(result.artifact)
        or _checked(
            stored[1],
            result.configuration.processing_configuration_sha256,
            MAX_CONFIGURATION_BYTES,
        )
        != projection.configuration_bytes
        or stored[2] != "1.1.0"
        or manifest is None
        or _checked(manifest[0], result.bank.manifest.sha256, MAX_MANIFEST_BYTES)
        != canonical_bytes(result.bank.manifest)
        or tuple(str(row[0]) for row in captures) != tuple(c.stored.id for c in result.captures)
    ):
        raise NumericalSourceError("The existing sealed job differs from this exact intake.")


def import_intake(
    source: NumericalRepository, plan: NativeIntakePlan, user: User
) -> NativeIntakeResult:
    """Durable source/capture checkpoints, followed by atomic existing producer sealing."""
    with source.connect() as connection, connection.transaction():
        _authorize(connection, user)
        ready = connection.execute(
            "SELECT to_regclass('regintel.native_parse_manifests'),"
            "to_regclass('regintel.numerical_page_captures')"
        ).fetchone()
        if ready is None or any(table is None for table in ready):
            raise NumericalSourceError("Native source intake migrations are required.")
    prepared = prepare_intake(plan)
    if prepared.baseline != source.configuration:
        raise NumericalSourceError("The selected parser differs from this intake repository.")
    with source.connect() as connection, connection.transaction():
        _authorize(connection, user)
        stage = source.storage.stage()
        try:
            stage.write(prepared.source_bytes)
            original = stage.finish()
        finally:
            stage.close()
    jobs = JobRepository(source.database)
    job = jobs.submit(
        original,
        plan.metadata,
        prepared.check.processing_configuration_sha256,
        user.id,
        user.auth_version,
        worker_dispatch=False,
    )
    if job.state in {"FAILED", "SOURCE_VERIFIED"}:
        raise NumericalSourceError("The existing native job has an incompatible terminal outcome.")
    if job.state == "PARSED":
        expected_ids = tuple(
            page_capture_id(job.filing_version_id, job.source_blob_id, digest)
            for digest in prepared.check.prepared_sha256
        )
        with source.connect() as connection, connection.transaction():
            _authorize(connection, user)
            stored_ids = connection.execute(
                "SELECT capture_id FROM regintel.native_parse_context_captures "
                "WHERE parse_version_id=%s ORDER BY page_index",
                (UUID(job.parse_version_id),),
            ).fetchall()
        if tuple(str(row[0]) for row in stored_ids) != expected_ids:
            raise NumericalSourceError("The sealed job retains different contextual captures.")
    captures = tuple(
        ContextCapture(
            source.save(job.filing_version_id, page.raw_bytes, selected.pdf_page, user),
            page.raw_bytes,
        )
        for page, selected in zip(prepared.pages, plan.context_pages, strict=True)
    )
    with source.connect() as connection:
        owner = connection.execute(
            "SELECT filing_id FROM regintel.filing_versions WHERE id=%s",
            (UUID(job.filing_version_id),),
        ).fetchone()
    if owner is None:
        raise NumericalSourceError("The submitted native filing is unavailable.")
    # A job/source/configuration has one parse identity, including concurrent retries.
    parse_id = job.parse_version_id or str(
        UUID(bytes=hashlib.sha256(("native-intake:" + job.id).encode()).digest()[:16], version=4)
    )
    result = build_native_context_parse(
        prepared.bank,
        source=source.storage.root / original.blob.storage_key,
        baseline=prepared.baseline,
        captures=captures,
        parse_id=parse_id,
        filing_id=str(owner[0]),
        filing_version_id=job.filing_version_id,
        source_blob_id=job.source_blob_id,
    )
    outcome = NativeM1Producer(source).run(job.id, result, user)
    _verify_sealed(source, result, job.id, user)
    return NativeIntakeResult(job=outcome, capture_ids=tuple(c.stored.id for c in captures))
