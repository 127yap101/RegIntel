"""Worker-only conversion of one verified immutable source snapshot."""

import os
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from regintel.evidence.source import read_verified_source
from regintel.ingestion.jobs import ParserFailure
from regintel.ingestion.models import SourceBlob
from regintel.ingestion.storage import SourceStorage, UploadError, inspect_pdf
from regintel.parsing.adapter import AdapterError, build_artifact
from regintel.parsing.configuration import (
    ParserRuntimeConfiguration,
    validate_runtime_configuration,
)
from regintel.parsing.geometry import CoordinateFrame
from regintel.parsing.models import ParseArtifact
from regintel.parsing.sdk import capture_conversion, create_converter


class ParserProcessor:
    def __init__(
        self, storage: SourceStorage, configuration: ParserRuntimeConfiguration, models: Path
    ) -> None:
        if not models.is_absolute():
            raise ValueError("An explicit absolute model root is required.")
        self.storage = storage
        self.configuration = configuration
        self.models = models

    def __call__(
        self, blob: SourceBlob, parse_id: str, filing_id: str, filing_version_id: str
    ) -> ParseArtifact:
        try:
            payload = read_verified_source(self.storage, blob)
        except OSError:
            raise UploadError(503, "SOURCE_UNAVAILABLE") from None
        page_count = inspect_pdf(BytesIO(payload), len(payload), self.storage.settings)
        # A private snapshot prevents source replacement between verification,
        # conversion and the adapter's geometry read. The original remains untouched.
        with TemporaryDirectory(prefix="regintel-parse-") as directory:
            snapshot = Path(directory) / "source.pdf"
            descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
            try:
                converter, resolved = create_converter(self.models)
                validate_runtime_configuration(
                    self.configuration, resolved_sdk_configuration=resolved
                )
            except Exception:
                raise ParserFailure("PARSER_CONFIGURATION_MISMATCH") from None
            try:
                captured = capture_conversion(converter, snapshot)
            except Exception:
                raise ParserFailure("PARSE_FAILED") from None
            captured["configuration"] = resolved
            captured["source_sha256"] = blob.sha256
            try:
                artifact = build_artifact(
                    captured,
                    source=snapshot,
                    source_sha256=blob.sha256,
                    parse_id=parse_id,
                    filing_id=filing_id,
                    filing_version_id=filing_version_id,
                    source_blob_id=blob.id,
                    coordinate_frame=CoordinateFrame(self.configuration.coordinate_frame),
                )
                if len(artifact.pages) != page_count:
                    raise ParserFailure("ARTIFACT_INVALID")
                return artifact
            except AdapterError:
                raise ParserFailure("ARTIFACT_INVALID") from None
