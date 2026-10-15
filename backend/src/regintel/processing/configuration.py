"""Explicit installed orchestration and stage identities, without provider calls."""

import hashlib
from pathlib import Path

from regintel.processing.models import ProcessingConfiguration


def current_configuration() -> ProcessingConfiguration:
    from regintel.candidates.extraction import current_configuration as candidates
    from regintel.entities.resolution import current_configuration as entities
    from regintel.validation.gate import current_configuration as validation

    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent.parent
    for relative in (
        "processing/models.py",
        "processing/configuration.py",
        "processing/repository.py",
        "processing/processor.py",
        "processing/broker.py",
        "processing/cli.py",
        "processing/api.py",
        "db/connections.py",
        "entities/repository.py",
        "candidates/repository.py",
        "validation/repository.py",
    ):
        contents = (root / relative).read_bytes()
        digest.update(relative.encode() + b"\0" + len(contents).to_bytes(8, "big") + contents)
    return ProcessingConfiguration(
        code_sha256=digest.hexdigest(),
        entity=entities(),
        candidate=candidates(),
        validation=validation(),
    )
