"""Explicit local seed/check/server entry points; no credentials in command arguments."""

import argparse
from pathlib import Path

import uvicorn

from regintel.auth.config import load_auth_settings, load_seed_accounts
from regintel.auth.errors import AuthUnavailable, InvalidAuthentication, SeedConflict
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.service import AuthService
from regintel.db.config import load_database_settings

ROOT = Path(__file__).resolve().parents[4]


def _parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--auth-env-file", type=Path, default=ROOT / ".env.auth")
    return parser


def main() -> None:
    parser = _parser("Seed or verify explicit local authentication configuration.")
    parser.add_argument("action", choices=("seed", "check"))
    args = parser.parse_args()
    try:
        database = load_database_settings(args.env_file)
        settings = load_auth_settings(args.auth_env_file)
        seeds = load_seed_accounts(args.auth_env_file)
        if args.action == "seed":
            report = seed_users(database, seeds)
            print(
                f"Seed complete: created {len(report.created)}, preserved {len(report.existing)}."
            )
        else:
            service = AuthService(PostgreSQLAuthRepository(database), settings)
            for account in seeds:
                token = service.login(account.username, account.password.get_secret_value())
                user = service.current_user(token)
                if user.username != account.username or user.role != account.role:
                    raise InvalidAuthentication("Seed identity mismatch.")
            print("Authentication check passed for both seeded roles; secrets omitted.")
    except (OSError, ValueError, AuthUnavailable, SeedConflict, InvalidAuthentication):
        raise SystemExit("Authentication command failed; configuration/secrets omitted.") from None


def serve_main() -> None:
    parser = _parser("Run the configured native API on loopback.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("The port must be between 1 and 65535.")
    try:
        service = AuthService(
            PostgreSQLAuthRepository(load_database_settings(args.env_file)),
            load_auth_settings(args.auth_env_file),
        )
    except (OSError, ValueError, AuthUnavailable):
        raise SystemExit("Authentication configuration is unavailable; secrets omitted.") from None
    from regintel.admin.repository import AdminRepository
    from regintel.candidates.api import CandidateService
    from regintel.candidates.repository import CandidateRepository
    from regintel.entities.api import EntityService
    from regintel.entities.repository import EntityRepository
    from regintel.evidence.api import EvidenceService
    from regintel.evidence.repository import EvidenceRepository
    from regintel.ingestion.api import IngestionService
    from regintel.ingestion.broker import create_celery, sender
    from regintel.ingestion.config import native_ingestion_settings
    from regintel.ingestion.repository import JobRepository
    from regintel.main import create_app
    from regintel.processing.api import ProcessingService
    from regintel.processing.broker import sender as processing_sender
    from regintel.processing.repository import ProcessingRepository
    from regintel.publication.graph import Neo4jProjection
    from regintel.publication.repository import PublicationRepository
    from regintel.publication.service import PublicationService, current_configuration
    from regintel.reads.repository import ReadRepository
    from regintel.reads.service import PublishedReadService
    from regintel.retrieval.graph import Neo4jExpansion
    from regintel.retrieval.repository import SearchRepository
    from regintel.retrieval.service import RetrievalService
    from regintel.validation.api import ValidationService
    from regintel.validation.repository import ValidationRepository

    ingestion_settings = native_ingestion_settings(ROOT, args.env_file)
    ingestion = IngestionService(
        ingestion_settings,
        JobRepository(load_database_settings(args.env_file)),
        sender(create_celery(ingestion_settings)),
    )

    model_root = ROOT / "models/bge-small-en-v1.5"
    publication = None
    graph = None
    if model_root.is_dir():
        try:
            configuration = current_configuration(model_root)
            graph = Neo4jProjection.from_env(args.env_file)
            publication = PublicationService(
                PublicationRepository(load_database_settings(args.env_file)),
                graph,
                configuration,
                model_root=model_root,
            )
        except (OSError, ValueError, ImportError):
            raise SystemExit("Publication prerequisites are invalid; secrets omitted.") from None

    evidence_service = EvidenceService(
        EvidenceRepository(load_database_settings(args.env_file)), ingestion.storage
    )
    read_service = PublishedReadService(
        PublicationRepository(load_database_settings(args.env_file)),
        ReadRepository(load_database_settings(args.env_file)),
        evidence_service,
        graph,
    )
    from regintel.learning.repository import LearningRepository
    from regintel.learning.service import LearningService
    from regintel.portfolio.repository import PortfolioRepository
    from regintel.portfolio.service import PortfolioService

    try:
        uvicorn.run(
            create_app(
                auth_service=service,
                admin_repository=AdminRepository(load_database_settings(args.env_file)),
                ingestion_service=ingestion,
                evidence_service=evidence_service,
                entity_service=EntityService(
                    EntityRepository(load_database_settings(args.env_file))
                ),
                candidate_service=CandidateService(
                    CandidateRepository(load_database_settings(args.env_file))
                ),
                validation_service=ValidationService(
                    ValidationRepository(load_database_settings(args.env_file))
                ),
                processing_service=ProcessingService(
                    ProcessingRepository(load_database_settings(args.env_file)),
                    processing_sender(create_celery(ingestion_settings)),
                ),
                publication_service=publication,
                read_service=read_service,
                learning_service=LearningService(
                    LearningRepository(load_database_settings(args.env_file)), read_service
                ),
                portfolio_service=PortfolioService(
                    PortfolioRepository(load_database_settings(args.env_file)), read_service
                ),
                retrieval_service=RetrievalService(
                    read_service,
                    SearchRepository(load_database_settings(args.env_file)),
                    Neo4jExpansion(graph) if graph is not None else None,
                    model_root=model_root if model_root.is_dir() else None,
                ),
            ),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
        )
    finally:
        if graph is not None:
            graph.close()
