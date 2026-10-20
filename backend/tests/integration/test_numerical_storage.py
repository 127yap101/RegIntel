"""Disposable PostgreSQL source preparation; authored captures are not gold data."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr

from backend.tests.test_numerical_source_pages import fixture, parts
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.types import SeedAccount, User
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import connect_database
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.jobs import UploadMetadata
from regintel.ingestion.repository import JobRepository
from regintel.ingestion.storage import SourceStorage
from regintel.numerical.models import NumericalWordRef, StoredNumericalPage, page_capture_id
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalRepository,
    NumericalSourceError,
)
from regintel.numerical.source_pages import build_page_capture, capture_bytes
from regintel.parsing.configuration import ParserRuntimeConfiguration

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True)
class Context:
    database: DatabaseSettings
    repository: NumericalRepository
    user: User
    learner: User
    filing: str
    blob: str
    source: Path
    raw: dict[str, object]
    config: ParserRuntimeConfiguration


@pytest.fixture
def numerical(auth_database: DatabaseSettings, tmp_path: Path) -> Context:
    source, raw, _, config_sha = fixture(tmp_path)
    config = ParserRuntimeConfiguration.model_validate_json(
        (ROOT / "data/parser-runtime-config.json").read_bytes()
    ).model_copy(update={"sdk_configuration_sha256": config_sha})
    seed_users(
        auth_database,
        (
            SeedAccount("admin", SecretStr("Authored numerical fixture password!"), "admin"),
            SeedAccount("learner", SecretStr("Authored numerical fixture password!"), "learner"),
        ),
    )
    accounts = PostgreSQLAuthRepository(auth_database)
    user, learner = accounts.get_by_username("admin"), accounts.get_by_username("learner")
    assert user is not None and learner is not None
    settings = IngestionSettings(
        source_root=tmp_path / "owned-sources",
        broker_url=SecretStr("redis://:authored@127.0.0.1:6379/0"),
    )
    storage = SourceStorage(settings)
    stage = storage.stage()
    stage.write(source.read_bytes())
    stored = stage.finish()
    job = JobRepository(auth_database).submit(
        stored,
        UploadMetadata(company_name_raw="Authored numerical issuer", document_type="RHP"),
        settings.configuration_sha256,
        user.id,
        user.auth_version,
    )
    return Context(
        auth_database,
        NumericalRepository(auth_database, storage, config),
        user,
        learner,
        job.filing_version_id,
        job.source_blob_id,
        storage.root / stored.blob.storage_key,
        raw,
        config,
    )


def save(context: Context) -> StoredNumericalPage:
    return context.repository.save(context.filing, canonical(context.raw), 2, context.user)


def counts(context: Context) -> tuple[object, ...]:
    with connect_database(context.database) as connection:
        row = connection.execute("""SELECT
            (SELECT count(*) FROM regintel.numerical_page_captures),
            (SELECT count(*) FROM regintel.numerical_source_words),
            (SELECT count(*) FROM regintel.acceptance_audits),
            (SELECT count(*) FROM regintel.fact_observations),
            (SELECT count(*) FROM regintel.parse_versions),
            (SELECT count(*) FROM regintel.corpus_versions)""").fetchone()
        assert row is not None
        return row


def test_roundtrip_replay_and_exact_word_reference_preserve_source(numerical: Context) -> None:
    before = numerical.source.read_bytes()
    saved = save(numerical)
    assert counts(numerical) == (1, 1, 0, 0, 0, 0)
    assert save(numerical) == saved
    assert numerical.repository.get(saved.id, numerical.user) == saved
    assert saved.capture.page_index == 1 and not saved.capture.acceptance_eligible
    ref = NumericalWordRef(capture_id=saved.id, word_index=0, start=0, end=9, quote="14,285.34")
    word = numerical.repository.resolve_word(ref, numerical.user)
    assert word.source_sha256 == saved.capture.source_sha256
    assert word.filing_version_id == numerical.filing and word.page_index == 1
    assert word.geometry_scope == "ORIGINAL_WORD_ENVELOPE"
    assert not word.acceptance_eligible and word.review_required
    partial = numerical.repository.resolve_word(
        NumericalWordRef(capture_id=saved.id, word_index=0, start=3, end=6, quote="285"),
        numerical.user,
    )
    assert partial.box == word.box and partial.raw_rectangle == word.raw_rectangle
    assert partial.geometry_scope == "ORIGINAL_WORD_ENVELOPE"
    assert numerical.source.read_bytes() == before
    assert counts(numerical) == (1, 1, 0, 0, 0, 0)


def test_concurrent_replay_stores_one_immutable_capture(numerical: Context) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: save(numerical), range(2)))
    assert results[0] == results[1]
    assert counts(numerical) == (1, 1, 0, 0, 0, 0)


def test_changed_parser_proposal_keeps_history_instead_of_overwriting(numerical: Context) -> None:
    original = save(numerical)
    word, cells = parts(numerical.raw)
    word["orig"] = "14,285.35"
    cells[0]["text"] = "14,285.35"
    changed = save(numerical)
    assert original.id != changed.id
    assert numerical.repository.get(original.id, numerical.user) == original
    assert original.capture.words[0].orig == "14,285.34"
    assert changed.capture.words[0].orig == "14,285.35"
    assert counts(numerical) == (2, 2, 0, 0, 0, 0)


@pytest.mark.parametrize("change", ["quote", "index", "ocr", "geometry"])
def test_word_resolution_never_invents_missing_support(numerical: Context, change: str) -> None:
    word, _ = parts(numerical.raw)
    if change == "ocr":
        word["from_ocr"] = True
    elif change == "geometry":
        word["rect"] = None
    saved = save(numerical)
    reference = NumericalWordRef(
        capture_id=saved.id,
        word_index=1 if change == "index" else 0,
        start=0,
        end=9,
        quote="14,285.35" if change == "quote" else "14,285.34",
    )
    with pytest.raises(NumericalSourceError):
        numerical.repository.resolve_word(reference, numerical.user)


@pytest.mark.parametrize("actor", ["learner", "inactive", "stale"])
def test_only_current_admins_can_store_or_read(numerical: Context, actor: str) -> None:
    saved = save(numerical)
    user = numerical.user
    if actor == "learner":
        user = replace(
            numerical.learner, role="admin"
        )  # A supplied role cannot elevate the DB user.
    else:
        with connect_database(numerical.database) as connection:
            if actor == "inactive":
                connection.execute(
                    "UPDATE regintel.users SET is_active=FALSE WHERE id=%s", (user.id,)
                )
            else:
                connection.execute(
                    "UPDATE regintel.users SET auth_version=auth_version+1 WHERE id=%s", (user.id,)
                )
    with pytest.raises(NumericalAuthorizationError):
        numerical.repository.save(numerical.filing, canonical(numerical.raw), 2, user)
    with pytest.raises(NumericalAuthorizationError):
        numerical.repository.get(saved.id, user)
    assert counts(numerical) == (1, 1, 0, 0, 0, 0)


@pytest.mark.parametrize("change", ["source", "raw_hash", "settings", "duplicate_keys", "depth"])
def test_invalid_source_or_raw_capture_rolls_back(numerical: Context, change: str) -> None:
    if change == "source":
        numerical.source.write_bytes(b"Altered authored source")
    elif change == "raw_hash":
        numerical.raw["original_source_sha256"] = "0" * 64
    elif change == "settings":
        cast(dict[str, object], numerical.raw["configuration"])["authored_options"] = "changed"
    raw = canonical(numerical.raw)
    if change == "duplicate_keys":
        raw = b'{"status":"success","status":"success"}'
    elif change == "depth":
        raw = b"[" * 2_000 + b"0" + b"]" * 2_000
    with pytest.raises(NumericalSourceError):
        numerical.repository.save(numerical.filing, raw, 2, numerical.user)
    assert counts(numerical) == (0, 0, 0, 0, 0, 0)


def test_database_rejects_capture_and_word_mutation(numerical: Context) -> None:
    save(numerical)
    statements = (
        "UPDATE regintel.numerical_page_captures SET page_index=page_index",
        "DELETE FROM regintel.numerical_page_captures",
        "TRUNCATE regintel.numerical_page_captures CASCADE",
        "UPDATE regintel.numerical_source_words SET word_bytes=word_bytes",
        "DELETE FROM regintel.numerical_source_words",
        "TRUNCATE regintel.numerical_source_words",
    )
    with connect_database(numerical.database) as connection:
        for statement in statements:
            with pytest.raises(psycopg.IntegrityError), connection.transaction():
                connection.execute(statement)
    assert counts(numerical) == (1, 1, 0, 0, 0, 0)


@pytest.mark.parametrize(
    "violation", ["incomplete", "word_hash", "word_content", "eligibility", "raw_hash", "actor"]
)
def test_direct_database_writes_cannot_bypass_atomic_sealing(
    numerical: Context, violation: str
) -> None:
    source_hash = hashlib.sha256(numerical.source.read_bytes()).hexdigest()
    capture = build_page_capture(
        numerical.raw,
        source=numerical.source,
        pdf_page=2,
        expected_source_sha256=source_hash,
        expected_sdk_configuration_sha256=numerical.config.sdk_configuration_sha256,
    )
    prepared, raw = capture_bytes(capture), canonical(numerical.raw)
    digest = hashlib.sha256(prepared).hexdigest()
    identity = page_capture_id(numerical.filing, numerical.blob, digest)
    values = (
        UUID(identity),
        UUID(numerical.filing),
        UUID(numerical.blob),
        source_hash,
        1,
        2,
        capture.sdk_configuration_sha256,
        capture.preparation_code_sha256,
        raw,
        "0" * 64 if violation == "raw_hash" else capture.raw_capture_sha256,
        prepared,
        digest,
        1,
        1,
        numerical.learner.id if violation == "actor" else numerical.user.id,
        numerical.user.auth_version,
        violation == "eligibility",
    )
    with connect_database(numerical.database) as connection:
        with pytest.raises(psycopg.IntegrityError), connection.transaction():
            connection.execute(
                """INSERT INTO regintel.numerical_page_captures
                (id,filing_version_id,source_blob_id,source_sha256,page_index,source_page_count,
                 sdk_configuration_sha256,preparation_code_sha256,raw_capture_bytes,
                 raw_capture_sha256,prepared_bytes,prepared_sha256,word_count,cell_count,
                 submitted_by,auth_version,acceptance_eligible)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                values,
            )
            if violation in {"word_hash", "word_content"}:
                word = capture.words[0].model_dump(mode="json")
                if violation == "word_content":
                    word["orig"] = "14,285.35"
                body = canonical(word)
                connection.execute(
                    """INSERT INTO regintel.numerical_source_words
                    (capture_id,word_index,word_bytes,word_sha256) VALUES(%s,0,%s,%s)""",
                    (
                        UUID(identity),
                        body,
                        "0" * 64 if violation == "word_hash" else hashlib.sha256(body).hexdigest(),
                    ),
                )
    assert counts(numerical) == (0, 0, 0, 0, 0, 0)
