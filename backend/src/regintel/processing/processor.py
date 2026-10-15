"""Resume frozen stages and atomically attach their domain results to a workflow."""

from collections.abc import Callable
from typing import Literal

from pydantic import ValidationError

from regintel.candidates.models import ExtractionInput
from regintel.candidates.records import CandidateRun
from regintel.candidates.repository import (
    CandidateAuthorizationError,
    CandidateConflict,
    CandidateNotFound,
    CandidateSourceError,
    CandidateUnavailable,
)
from regintel.contracts.models import ContractModel
from regintel.db.migrations import DatabaseConnection
from regintel.entities.models import EntityRun, canonical_bytes
from regintel.entities.repository import (
    EntityAuthorizationError,
    EntityConflict,
    EntityNotFound,
    EntityRegistryChanged,
    EntitySourceError,
    EntityUnavailable,
)
from regintel.entities.resolution import EntityResolver
from regintel.processing.configuration import current_configuration
from regintel.processing.models import STAGES, EntityStageInput, FailureCode, ProcessingJob, Stage
from regintel.processing.repository import (
    UNAVAILABLE,
    ProcessingConflict,
    ProcessingFailure,
    ProcessingFenced,
    ProcessingNotFound,
    ProcessingRepository,
    ProcessingUnavailable,
    digest,
    lock_key,
)
from regintel.validation.models import ValidationInput, ValidationRun
from regintel.validation.repository import (
    ValidationAuthorizationError,
    ValidationConflict,
    ValidationNotFound,
    ValidationRepository,
    ValidationSourceError,
    ValidationUnavailable,
)

type BoundaryHook = Callable[[Stage, Literal["frozen", "checkpointed"]], None]


class Processor:
    def __init__(
        self, repository: ProcessingRepository, *, boundary: BoundaryHook | None = None
    ) -> None:
        self.repository = repository
        self.entities = repository.entities
        self.candidates = repository.candidates
        self.validator = ValidationRepository(
            repository.database, connection_factory=repository.connect
        )
        self.boundary = boundary

    def _boundary(self, stage: Stage, where: Literal["frozen", "checkpointed"]) -> None:
        if self.boundary is not None:
            self.boundary(stage, where)

    @staticmethod
    def _output(job: ProcessingJob, stage: Stage) -> str:
        return next(item.output_id for item in job.checkpoints if item.stage == stage)

    def _stage(self, job: ProcessingJob, stage: Stage) -> None:
        user = self.repository.user(job)
        payload = self.repository.input(job.id, stage)
        if payload is None:
            value: ContractModel
            if stage == "ENTITY":
                evidence, artifact_sha = self.entities.evidence_for_parse(
                    job.request.parse_version_id
                )
                value = EntityStageInput(
                    parse_version_id=job.request.parse_version_id,
                    artifact_sha256=artifact_sha,
                    evidence=evidence,
                    registry=self.entities.snapshot(),
                    configuration=job.configuration.entity,
                )
            elif stage == "CANDIDATE":
                value = self.candidates.input_for_run(
                    self._output(job, "ENTITY"), job.request.metric_ids
                )
            else:
                value = self.validator.input_for_run(self._output(job, "CANDIDATE"))
            cfg_sha = getattr(job.configuration, stage.lower()).sha256
            payload = self.repository.freeze(job, stage, canonical_bytes(value), cfg_sha)
        self._boundary(stage, "frozen")
        input_sha = digest(payload)
        if stage == "ENTITY":
            frozen_entity = EntityStageInput.model_validate_json(payload)
            if (
                frozen_entity.configuration != job.configuration.entity
                or frozen_entity.parse_version_id != job.request.parse_version_id
            ):
                raise ProcessingFailure("SOURCE_INVALID")
            run = EntityResolver(frozen_entity.registry, frozen_entity.configuration).run(
                frozen_entity.evidence, frozen_entity.artifact_sha256
            )

            def entity_completed(connection: DatabaseConnection, actual: EntityRun) -> None:
                if actual != run or actual.configuration != job.configuration.entity:
                    raise ProcessingFailure("INPUT_CHANGED")
                self.repository.checkpoint(
                    connection, job, stage, actual.id, input_sha, job.configuration.entity.sha256
                )

            self.entities.save_run(run, user, on_completed=entity_completed)
        elif stage == "CANDIDATE":
            frozen_candidate = ExtractionInput.model_validate_json(payload)
            if (
                frozen_candidate.entity_run.id != self._output(job, "ENTITY")
                or frozen_candidate.parse_version_id != job.request.parse_version_id
                or tuple(sorted(metric.id for metric in frozen_candidate.metrics))
                != job.request.metric_ids
            ):
                raise ProcessingFailure("SOURCE_INVALID")
            if (
                self.candidates.input_for_run(
                    self._output(job, "ENTITY"), job.request.metric_ids
                ).sha256
                != input_sha
            ):
                raise ProcessingFailure("INPUT_CHANGED")

            def candidate_completed(connection: DatabaseConnection, actual: CandidateRun) -> None:
                if (
                    actual.input_sha256 != input_sha
                    or actual.configuration != job.configuration.candidate
                ):
                    raise ProcessingFailure("INPUT_CHANGED")
                self.repository.checkpoint(
                    connection, job, stage, actual.id, input_sha, job.configuration.candidate.sha256
                )

            self.candidates.extract(
                self._output(job, "ENTITY"),
                job.request.metric_ids,
                user,
                on_completed=candidate_completed,
            )
        else:
            frozen_validation = ValidationInput.model_validate_json(payload)
            if (
                frozen_validation.candidate_run.id != self._output(job, "CANDIDATE")
                or frozen_validation.candidate_run.parse_version_id != job.request.parse_version_id
            ):
                raise ProcessingFailure("SOURCE_INVALID")
            if self.validator.input_for_run(self._output(job, "CANDIDATE")).sha256 != input_sha:
                raise ProcessingFailure("INPUT_CHANGED")

            def validation_completed(connection: DatabaseConnection, actual: ValidationRun) -> None:
                if (
                    actual.input_sha256 != input_sha
                    or actual.configuration != job.configuration.validation
                ):
                    raise ProcessingFailure("INPUT_CHANGED")
                self.repository.checkpoint(
                    connection,
                    job,
                    stage,
                    actual.id,
                    input_sha,
                    job.configuration.validation.sha256,
                )

            self.validator.validate(
                self._output(job, "CANDIDATE"), user, on_completed=validation_completed
            )
        self._boundary(stage, "checkpointed")

    def _execute(self, job: ProcessingJob) -> None:
        try:
            for stage in STAGES:
                if current_configuration() != job.configuration:
                    raise ProcessingFailure("CONFIGURATION_CHANGED")
                if not any(item.stage == stage for item in job.checkpoints):
                    self._stage(job, stage)
                    refreshed = self.repository.get(job.id)
                    if refreshed is None or refreshed.generation != job.generation:
                        raise ProcessingFenced("The attempt was replaced.")
                    job = refreshed
            self.repository.finish(job)
        except ProcessingFenced:
            return
        except Exception as error:
            # Repository adapters sanitize their public exceptions. Inspect only
            # exception types in the local chain; never persist private messages.
            cause: BaseException | None = error
            visited: set[int] = set()
            temporary = False
            while cause is not None and id(cause) not in visited:
                visited.add(id(cause))
                if isinstance(
                    cause,
                    (
                        *UNAVAILABLE,
                        EntityUnavailable,
                        CandidateUnavailable,
                        ValidationUnavailable,
                        ProcessingUnavailable,
                    ),
                ):
                    temporary = True
                    break
                cause = cause.__cause__ or cause.__context__
            if temporary:
                try:
                    self.repository.retry(job)
                except (*UNAVAILABLE, ProcessingFenced, ProcessingUnavailable):
                    pass
                raise ProcessingUnavailable("Processing storage temporarily unavailable.") from None
            code: FailureCode
            if isinstance(error, ProcessingFailure):
                code = error.code
            elif isinstance(
                error,
                (
                    EntityAuthorizationError,
                    CandidateAuthorizationError,
                    ValidationAuthorizationError,
                ),
            ):
                code = "AUTHORIZATION_CHANGED"
            elif isinstance(
                error,
                (
                    EntityRegistryChanged,
                    EntityConflict,
                    CandidateConflict,
                    ValidationConflict,
                    ProcessingConflict,
                ),
            ):
                code = "INPUT_CHANGED"
            elif isinstance(
                error,
                (
                    EntitySourceError,
                    CandidateSourceError,
                    ValidationSourceError,
                    ValidationError,
                    EntityNotFound,
                    CandidateNotFound,
                    ValidationNotFound,
                    ProcessingNotFound,
                    ValueError,
                ),
            ):
                code = "SOURCE_INVALID"
            else:
                code = "PROCESSING_FAILED"
            try:
                self.repository.fail(job, code)
            except ProcessingFenced:
                return

    def run(self, job_id: str) -> None:
        try:
            with self.repository.connect() as control:
                acquired = control.execute(
                    "SELECT pg_try_advisory_lock(%s)", (lock_key(job_id),)
                ).fetchone()
                if acquired != (True,):
                    return
                try:
                    job = self.repository.claim(control, job_id)
                    if job is not None:
                        self._execute(job)
                finally:
                    if not control.closed:
                        control.execute("SELECT pg_advisory_unlock(%s)", (lock_key(job_id),))
        except ProcessingFenced:
            return
        except (*UNAVAILABLE, ProcessingUnavailable):
            raise ProcessingUnavailable("Processing storage temporarily unavailable.") from None
