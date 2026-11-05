"""Explicit local seed/check/server entry points; no credentials in command arguments."""

import argparse
import json
from pathlib import Path

import uvicorn

from regintel.auth.config import load_auth_settings, load_seed_accounts
from regintel.auth.errors import AuthUnavailable, InvalidAuthentication, SeedConflict
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.service import AuthService
from regintel.db.config import load_database_settings
from regintel.db.migrations import MigrationError, migration_status

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
    parser.add_argument(
        "--asset-project",
        type=Path,
        default=ROOT,
        help="Explicit project containing data/uploads, parser configuration and models.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate schema/configuration without starting services or changing data.",
    )
    parser.add_argument(
        "--numerical-runtime-file",
        type=Path,
        help="Selected native numerical parser descriptor; omitted disables numerical review HTTP.",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("The port must be between 1 and 65535.")
    try:
        assets = args.asset_project.resolve(strict=True)
        if not assets.is_dir():
            raise ValueError("The selected asset project must be a directory.")
        database = load_database_settings(args.env_file)
        schema = migration_status(database)
        if schema.pending:
            raise SystemExit(
                f"Database has {len(schema.pending)} pending migrations for this checkout. "
                "Run regintel-db migrate with this checkout and the selected --env-file "
                "before starting the API. No migration was applied."
            )
        service = AuthService(
            PostgreSQLAuthRepository(database),
            load_auth_settings(args.auth_env_file),
        )
        from regintel.ingestion.config import native_ingestion_settings
        from regintel.parsing.configuration import (
            current_runtime_code_hashes,
            load_runtime_configuration,
        )

        ingestion_settings = native_ingestion_settings(assets, args.env_file)
        numerical_configuration = (
            load_runtime_configuration(args.numerical_runtime_file)
            if args.numerical_runtime_file is not None
            else None
        )
        if numerical_configuration is not None and any(
            getattr(numerical_configuration, name) != digest
            for name, digest in current_runtime_code_hashes().model_dump().items()
        ):
            raise ValueError("The numerical descriptor differs from installed parser code.")
    except (OSError, ValueError, AuthUnavailable, MigrationError):
        raise SystemExit(
            "API configuration/schema check failed. Verify the selected asset project, "
            "environment files, parser descriptors and migration history; secrets omitted."
        ) from None

    model_root = assets / "models/bge-small-en-v1.5"
    if args.check:
        print(
            json.dumps(
                {
                    "status": "CONFIGURATION_VALIDATED",
                    "database_schema_version": schema.applied[-1],
                    "asset_project": str(assets),
                    "source_directory_present": ingestion_settings.source_root.is_dir(),
                    "publication_model_directory_present": model_root.is_dir(),
                    "numerical_review_configured": numerical_configuration is not None,
                    "processing_configuration_sha256": ingestion_settings.configuration_sha256,
                    "live_services_checked": False,
                    "authentication_checked": False,
                    "content_approved": False,
                }
            )
        )
        return
    from regintel.admin.repository import AdminRepository
    from regintel.candidates.api import CandidateService
    from regintel.candidates.repository import CandidateRepository
    from regintel.entities.api import EntityService
    from regintel.entities.repository import EntityRepository
    from regintel.evidence.api import EvidenceService
    from regintel.evidence.repository import EvidenceRepository
    from regintel.ingestion.api import IngestionService
    from regintel.ingestion.broker import create_celery, sender
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

    ingestion = IngestionService(
        ingestion_settings,
        JobRepository(database),
        sender(create_celery(ingestion_settings)),
    )
    from regintel.numerical.repository import NumericalRepository
    from regintel.numerical.review_repository import NumericalContextReviewRepository

    numerical_source = (
        NumericalRepository(
            database,
            ingestion.storage,
            numerical_configuration,
        )
        if numerical_configuration is not None
        else None
    )

    publication = None
    graph = None
    if model_root.is_dir():
        try:
            configuration = current_configuration(model_root)
            graph = Neo4jProjection.from_env(args.env_file)
            publication = PublicationService(
                PublicationRepository(database, numerical_source),
                graph,
                configuration,
                model_root=model_root,
            )
        except (OSError, ValueError, ImportError):
            raise SystemExit("Publication prerequisites are invalid; secrets omitted.") from None

    evidence_service = EvidenceService(EvidenceRepository(database), ingestion.storage)
    read_service = PublishedReadService(
        PublicationRepository(database),
        ReadRepository(database),
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
                admin_repository=AdminRepository(database),
                ingestion_service=ingestion,
                evidence_service=evidence_service,
                entity_service=EntityService(EntityRepository(database)),
                candidate_service=CandidateService(CandidateRepository(database)),
                validation_service=ValidationService(ValidationRepository(database)),
                processing_service=ProcessingService(
                    ProcessingRepository(database),
                    processing_sender(create_celery(ingestion_settings)),
                ),
                publication_service=publication,
                read_service=read_service,
                learning_service=LearningService(LearningRepository(database), read_service),
                portfolio_service=PortfolioService(PortfolioRepository(database), read_service),
                numerical_review_repository=NumericalContextReviewRepository(numerical_source)
                if numerical_source is not None
                else None,
                retrieval_service=RetrievalService(
                    read_service,
                    SearchRepository(database),
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
