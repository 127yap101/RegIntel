"""Administrator-only exact evidence and verified original-source HTTP endpoints."""

from typing import Annotated, Protocol

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from regintel.auth.dependencies import user_dependency
from regintel.auth.service import AuthService
from regintel.auth.types import User
from regintel.contracts.http import response_meta
from regintel.contracts.models import (
    ContractModel,
    ErrorEnvelope,
    SuccessEnvelope,
    TextEvidence,
)
from regintel.contracts.primitives import CanonicalId, Sha256Hash
from regintel.evidence.http import source_response
from regintel.evidence.source import read_verified_source
from regintel.ingestion.models import SourceBlob
from regintel.ingestion.storage import SourceStorage, UploadError
from regintel.parsing.models import ParseProvenance


class EvidenceReader(Protocol):
    def get_evidence(
        self, evidence_id: str
    ) -> tuple[TextEvidence, ParseProvenance, str, str] | None: ...

    def get_source(self, filing_version_id: str) -> SourceBlob | None: ...


class EvidenceData(ContractModel):
    record: TextEvidence
    provenance: ParseProvenance
    source_sha256: Sha256Hash
    processing_configuration_sha256: Sha256Hash


class EvidenceEnvelope(SuccessEnvelope[EvidenceData]):
    pass


class EvidenceService:
    def __init__(self, repository: EvidenceReader, storage: SourceStorage) -> None:
        self.repository = repository
        self.storage = storage


def create_evidence_router(auth: AuthService | None, service: EvidenceService | None) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["filing evidence"])
    admin = user_dependency(auth, admin=True)

    def configured() -> EvidenceService:
        if service is None:
            raise HTTPException(503, "Evidence is unavailable.")
        return service

    errors: dict[int | str, dict[str, object]] = {
        code: {"model": ErrorEnvelope} for code in (400, 401, 403, 404, 416, 422, 500, 503)
    }

    @router.get("/evidence/{evidence_id}", response_model=EvidenceEnvelope, responses=errors)
    def evidence(
        request: Request,
        evidence_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        evidence_service: Annotated[EvidenceService, Depends(configured)],
    ) -> EvidenceEnvelope:
        try:
            result = evidence_service.repository.get_evidence(evidence_id)
        except (psycopg.Error, OSError, ValueError):
            raise HTTPException(503, "Evidence is unavailable.") from None
        if result is None:
            raise HTTPException(404, "Evidence not found.")
        record, provenance, source_sha256, processing_sha256 = result
        meta = response_meta(request)
        return EvidenceEnvelope(
            data=EvidenceData(
                record=record,
                provenance=provenance,
                source_sha256=source_sha256,
                processing_configuration_sha256=processing_sha256,
            ),
            meta=meta.model_copy(
                update={
                    "versions": meta.versions.model_copy(
                        update={
                            "filing_version_id": record.source.filing_version_id,
                            "parse_version_id": record.source.parse_version_id,
                        }
                    )
                }
            ),
        )

    source_responses: dict[int | str, dict[str, object]] = {
        **errors,
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}},
        206: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}},
        304: {"description": "Authenticated source has a matching entity tag."},
    }

    @router.get(
        "/filing-versions/{filing_version_id}/source.pdf",
        response_class=Response,
        responses=source_responses,
    )
    @router.head(
        "/filing-versions/{filing_version_id}/source.pdf",
        response_class=Response,
        responses=source_responses,
    )
    def source_pdf(
        request: Request,
        filing_version_id: CanonicalId,
        user: Annotated[User, Depends(admin)],
        evidence_service: Annotated[EvidenceService, Depends(configured)],
    ) -> Response:
        # Dependencies authenticate against current authoritative account state
        # before any repository lookup, file read, hashing or conditional result.
        try:
            blob = evidence_service.repository.get_source(filing_version_id)
            if blob is None:
                raise HTTPException(404, "Source not found.")
            data = read_verified_source(evidence_service.storage, blob)
        except (psycopg.Error, OSError, UploadError, ValueError):
            raise HTTPException(503, "Source is unavailable.") from None
        return source_response(request, data, blob.sha256)

    return router
