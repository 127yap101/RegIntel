"""PostgreSQL-owned requests, frozen inputs, fenced checkpoints and dispatch."""

import hashlib
from collections.abc import Callable
from uuid import UUID, uuid4

import psycopg
from pydantic import SecretStr

from regintel.auth.types import User
from regintel.candidates.repository import CandidateRepository
from regintel.db.config import DatabaseSettings
from regintel.db.connections import ConnectionFactory
from regintel.db.migrations import DatabaseConnection, MigrationError, connect_database
from regintel.entities.models import canonical_bytes
from regintel.entities.repository import EntityRepository
from regintel.processing.models import (
    FailureCode,
    ProcessingConfiguration,
    ProcessingJob,
    ProcessingRequest,
    Stage,
)


class ProcessingConflict(ValueError):
    """An immutable request, input or result conflicts."""


class ProcessingNotFound(ValueError):
    """The requested workflow/source is unavailable."""


class ProcessingFenced(RuntimeError):
    """A late attempt must abandon writes without changing the current attempt."""


class ProcessingFailure(RuntimeError):
    def __init__(self, code: FailureCode) -> None:
        self.code = code
        super().__init__(code)


class ProcessingUnavailable(RuntimeError):
    """A sanitized temporary storage prerequisite failure."""


UNAVAILABLE = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
    psycopg.errors.UndefinedTable,
    psycopg.errors.UndefinedColumn,
    psycopg.errors.DeadlockDetected,
    psycopg.errors.SerializationFailure,
    MigrationError,
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def checked(value: object, sha: object) -> bytes:
    if not isinstance(value, (bytes, memoryview)):
        raise ProcessingConflict("Stored processing payload is invalid.")
    payload = bytes(value)
    if not 0 < len(payload) <= 64_000_000 or digest(payload) != sha:
        raise ProcessingConflict("Stored processing fingerprint is invalid.")
    return payload


def lock_key(job_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(("processing:" + job_id).encode()).digest()[:8], "big", signed=True
    )


def authorize(connection: DatabaseConnection, user: User) -> None:
    row = connection.execute(
        "SELECT role,is_active,auth_version FROM regintel.users WHERE id=%s FOR SHARE",
        (user.id,),
    ).fetchone()
    if row != ("admin", True, user.auth_version):
        raise ProcessingFailure("AUTHORIZATION_CHANGED")


class ProcessingRepository:
    def __init__(
        self, database: DatabaseSettings, *, connection_factory: ConnectionFactory | None = None
    ) -> None:
        self.database = database
        self._connection_factory = connection_factory
        self.entities = EntityRepository(database, connection_factory=connection_factory)
        self.candidates = CandidateRepository(database, connection_factory=connection_factory)

    def connect(self) -> DatabaseConnection:
        if self._connection_factory is not None:
            return self._connection_factory()
        return connect_database(self.database)

    @staticmethod
    def _event(
        connection: DatabaseConnection,
        job_id: str,
        generation: int,
        kind: str,
        stage: Stage | None = None,
        failure_code: str | None = None,
    ) -> None:
        connection.execute(
            """INSERT INTO regintel.processing_events
            (job_id,sequence,generation,kind,stage,failure_code)
            SELECT %s,coalesce(max(sequence),0)+1,%s,%s,%s,%s
            FROM regintel.processing_events WHERE job_id=%s""",
            (job_id, generation, kind, stage, failure_code, job_id),
        )

    @staticmethod
    def current(connection: DatabaseConnection, job_id: str, generation: int) -> None:
        row = connection.execute(
            "SELECT state,generation FROM regintel.processing_jobs WHERE id=%s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if row != ("RUNNING", generation):
            raise ProcessingFenced("Attempt is no longer current.")

    @staticmethod
    def _get(connection: DatabaseConnection, job_id: str) -> ProcessingJob | None:
        row = connection.execute(
            """SELECT id,request_bytes,request_sha256,configuration_bytes,configuration_sha256,
            submitted_by,submitted_auth_version,state,generation,failure_code
            FROM regintel.processing_jobs WHERE id=%s""",
            (UUID(job_id),),
        ).fetchone()
        if row is None:
            return None
        request = ProcessingRequest.model_validate_json(checked(row[1], row[2]))
        configuration = ProcessingConfiguration.model_validate_json(checked(row[3], row[4]))
        if configuration.sha256 != row[4]:
            raise ProcessingConflict("Stored workflow configuration differs.")
        checkpoint_rows = connection.execute(
            """SELECT stage,output_id,input_sha256,configuration_sha256,generation
            FROM regintel.processing_checkpoints WHERE job_id=%s ORDER BY stage_index""",
            (job_id,),
        ).fetchall()
        event_rows = connection.execute(
            """SELECT sequence,generation,kind,stage,failure_code FROM regintel.processing_events
            WHERE job_id=%s ORDER BY sequence""",
            (job_id,),
        ).fetchall()
        return ProcessingJob.model_validate(
            {
                "id": str(row[0]),
                "request": request,
                "configuration": configuration,
                "submitted_by": str(row[5]),
                "submitted_auth_version": row[6],
                "state": row[7],
                "generation": row[8],
                "failure_code": row[9],
                "checkpoints": tuple(
                    dict(
                        zip(
                            (
                                "stage",
                                "output_id",
                                "input_sha256",
                                "configuration_sha256",
                                "generation",
                            ),
                            (r[0], str(r[1]), r[2], r[3], r[4]),
                            strict=True,
                        )
                    )
                    for r in checkpoint_rows
                ),
                "events": tuple(
                    dict(
                        zip(
                            ("sequence", "generation", "kind", "stage", "failure_code"),
                            r,
                            strict=True,
                        )
                    )
                    for r in event_rows
                ),
            }
        )

    def get(self, job_id: str) -> ProcessingJob | None:
        try:
            with self.connect() as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return self._get(connection, job_id)
        except UNAVAILABLE:
            raise ProcessingUnavailable("Processing storage is unavailable.") from None

    def submit(self, request: ProcessingRequest, user: User) -> ProcessingJob:
        from regintel.processing.configuration import current_configuration

        request = ProcessingRequest.model_validate(request.model_dump(mode="python"))
        payload = canonical_bytes(request)
        try:
            with self.connect() as connection, connection.transaction():
                authorize(connection, user)
                connection.execute(
                    "SELECT pg_advisory_xact_lock(%s)", (lock_key(request.idempotency_key),)
                )
                existing = connection.execute(
                    "SELECT id,request_bytes,request_sha256 FROM regintel.processing_jobs "
                    "WHERE idempotency_key=%s",
                    (request.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if checked(existing[1], existing[2]) != payload:
                        raise ProcessingConflict("The original request key has different data.")
                    job = self._get(connection, str(existing[0]))
                    if job is None:
                        raise ProcessingNotFound("Workflow is unavailable.")
                    return job
                # These reads verify sealed exact evidence and immutable metric membership.
                self.entities.evidence_for_parse(request.parse_version_id)
                self.candidates.metrics(request.metric_ids)
                configuration = current_configuration()
                config_bytes = canonical_bytes(configuration)
                job_id = str(uuid4())
                connection.execute(
                    """INSERT INTO regintel.processing_jobs
                    (id,idempotency_key,parse_version_id,request_bytes,request_sha256,
                     configuration_bytes,configuration_sha256,submitted_by,submitted_auth_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        job_id,
                        request.idempotency_key,
                        request.parse_version_id,
                        payload,
                        digest(payload),
                        config_bytes,
                        configuration.sha256,
                        user.id,
                        user.auth_version,
                    ),
                )
                connection.execute(
                    "INSERT INTO regintel.processing_dispatch(job_id) VALUES(%s)", (job_id,)
                )
                job = self._get(connection, job_id)
                if job is None:
                    raise ProcessingNotFound("Workflow is unavailable.")
                return job
        except UNAVAILABLE:
            raise ProcessingUnavailable("Processing storage is unavailable.") from None
        except psycopg.errors.UniqueViolation:
            raise ProcessingConflict("Immutable workflow identity conflicts.") from None

    def user(self, job: ProcessingJob) -> User:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id,username,role,is_active,auth_version FROM regintel.users WHERE id=%s",
                (job.submitted_by,),
            ).fetchone()
        if row is None or row[2:] != ("admin", True, job.submitted_auth_version):
            raise ProcessingFailure("AUTHORIZATION_CHANGED")
        if not isinstance(row[1], str):
            raise ProcessingFailure("AUTHORIZATION_CHANGED")
        return User(
            UUID(str(row[0])),
            row[1],
            SecretStr("unused"),
            "admin",
            True,
            job.submitted_auth_version,
        )

    def claim(self, connection: DatabaseConnection, job_id: str) -> ProcessingJob | None:
        with connection.transaction():
            job = self._get(connection, job_id)
            if job is None or job.state in {"SUCCEEDED", "FAILED"}:
                return None
            connection.execute(
                "UPDATE regintel.processing_jobs SET state='RUNNING',generation=generation+1 "
                "WHERE id=%s",
                (job_id,),
            )
            generation = job.generation + 1
            self._event(connection, job_id, generation, "STARTED")
            return self._get(connection, job_id)

    def input(self, job_id: str, stage: Stage) -> bytes | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT input_bytes,input_sha256 FROM regintel.processing_inputs "
                "WHERE job_id=%s AND stage=%s",
                (job_id, stage),
            ).fetchone()
        return None if row is None else checked(row[0], row[1])

    def freeze(self, job: ProcessingJob, stage: Stage, payload: bytes, config_sha: str) -> bytes:
        if not 0 < len(payload) <= 64_000_000:
            raise ProcessingFailure("SOURCE_INVALID")
        with self.connect() as connection, connection.transaction():
            self.current(connection, job.id, job.generation)
            row = connection.execute(
                "SELECT input_bytes,input_sha256 FROM regintel.processing_inputs "
                "WHERE job_id=%s AND stage=%s",
                (job.id, stage),
            ).fetchone()
            if row is not None:
                actual = checked(row[0], row[1])
                if actual != payload:
                    raise ProcessingFailure("INPUT_CHANGED")
                return actual
            connection.execute(
                """INSERT INTO regintel.processing_inputs
                (job_id,stage,input_bytes,input_sha256,configuration_sha256,generation)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (job.id, stage, payload, digest(payload), config_sha, job.generation),
            )
            self._event(connection, job.id, job.generation, "INPUT_FROZEN", stage)
            return payload

    def checkpoint(
        self,
        connection: DatabaseConnection,
        job: ProcessingJob,
        stage: Stage,
        output_id: str,
        input_sha: str,
        config_sha: str,
    ) -> None:
        self.current(connection, job.id, job.generation)
        connection.execute(
            """INSERT INTO regintel.processing_checkpoints
            (job_id,stage,output_id,input_sha256,configuration_sha256,generation)
            VALUES(%s,%s,%s,%s,%s,%s)""",
            (job.id, stage, output_id, input_sha, config_sha, job.generation),
        )
        self._event(connection, job.id, job.generation, "CHECKPOINT", stage)

    def fail(self, job: ProcessingJob, code: FailureCode) -> None:
        with self.connect() as connection, connection.transaction():
            self.current(connection, job.id, job.generation)
            connection.execute(
                "UPDATE regintel.processing_jobs SET state='FAILED',failure_code=%s WHERE id=%s",
                (code, job.id),
            )
            self._event(connection, job.id, job.generation, "FAILED", failure_code=code)

    def retry(self, job: ProcessingJob) -> None:
        with self.connect() as connection, connection.transaction():
            self.current(connection, job.id, job.generation)
            self._event(
                connection, job.id, job.generation, "RETRY", failure_code="STORAGE_UNAVAILABLE"
            )

    def finish(self, job: ProcessingJob) -> None:
        with self.connect() as connection, connection.transaction():
            self.current(connection, job.id, job.generation)
            authorize(connection, self.user(job))
            connection.execute(
                "UPDATE regintel.processing_jobs SET state='SUCCEEDED' WHERE id=%s", (job.id,)
            )
            self._event(connection, job.id, job.generation, "COMPLETED")

    def dispatch(
        self,
        sender: Callable[[str], None],
        *,
        job_id: str | None = None,
        limit: int = 100,
        user: User | None = None,
    ) -> int:
        if not 1 <= limit <= 100:
            raise ValueError("Dispatch batch must be bounded.")
        sent = 0
        try:
            with self.connect() as connection, connection.transaction():
                if user is not None:
                    authorize(connection, user)
                rows = connection.execute(
                    """SELECT d.job_id FROM regintel.processing_dispatch d
                    JOIN regintel.processing_jobs j ON j.id=d.job_id
                    WHERE j.state IN ('QUEUED','RUNNING') AND (%s::uuid IS NULL OR j.id=%s)
                    ORDER BY d.job_id FOR UPDATE OF d SKIP LOCKED LIMIT %s""",
                    (job_id, job_id, limit),
                ).fetchall()
                for row in rows:
                    identifier = str(row[0])
                    acquired = connection.execute(
                        "SELECT pg_try_advisory_lock(%s)", (lock_key(identifier),)
                    ).fetchone()
                    if acquired != (True,):
                        continue
                    # Check for a live attempt, then release before publishing:
                    # an immediate consumer must be able to claim this job. The
                    # outbox row lock still serializes concurrent dispatchers.
                    connection.execute("SELECT pg_advisory_unlock(%s)", (lock_key(identifier),))
                    try:
                        sender(identifier)
                    except Exception:
                        connection.execute(
                            "UPDATE regintel.processing_dispatch SET attempts=attempts+1,"
                            "last_failure_code='BROKER_UNAVAILABLE' WHERE job_id=%s",
                            (identifier,),
                        )
                    else:
                        connection.execute(
                            "UPDATE regintel.processing_dispatch SET attempts=attempts+1,"
                            "sent_at=clock_timestamp(),last_failure_code=NULL WHERE job_id=%s",
                            (identifier,),
                        )
                        sent += 1
        except UNAVAILABLE:
            raise ProcessingUnavailable("Processing dispatch is unavailable.") from None
        return sent
