"""Actual public native schemas keep nested safe-integer bounds in standard form."""

import runpy
from pathlib import Path

from regintel.numerical.evidence_binding_models import BoundNumericalCell, BoundNumericalPhrase
from regintel.numerical.models import NumericalWordRef


def test_native_schema_bounds_survive_json_schema_export():
    clean = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/export-contracts.py")
    )["remove_openapi_annotations"]
    cell = BoundNumericalCell.model_json_schema(mode="serialization")
    phrase = BoundNumericalPhrase.model_json_schema(mode="serialization")
    word = NumericalWordRef.model_json_schema(mode="serialization")
    for schema in (cell, phrase, word):
        clean(schema)
    assert cell["properties"]["row_span"]["minimum"] == 1
    assert cell["properties"]["column_span"]["minimum"] == 1
    assert phrase["properties"]["ordinal"]["maximum"] == 3
    assert word["properties"]["end"]["maximum"] == 20000
    assert word["properties"]["word_index"]["maximum"] == 19999
    for properties in (cell["properties"], phrase["properties"], word["properties"]):
        assert all("ge" not in value and "le" not in value for value in properties.values())
