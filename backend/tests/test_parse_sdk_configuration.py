"""Cross-process set metadata must not change parser processing identity."""

import hashlib
import json
from copy import deepcopy

import pytest

from regintel.parsing.sdk import canonical_pipeline_options


def digest(options: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(canonical_pipeline_options(options), sort_keys=True).encode()
    ).hexdigest()


def test_unordered_sdk_engine_metadata_is_canonical_without_mutating_capture() -> None:
    first: dict[str, object] = {
        "chart_extraction_options": {
            "model_spec": {"supported_engines": ["transformers", "api_openai", "api_ollama"]}
        },
        "ocr_options": {"lang": ["en", "hi"]},
        "code_formula_options": {"model_spec": {"supported_engines": None}},
    }
    original = deepcopy(first)
    second: dict[str, object] = {
        "chart_extraction_options": {
            "model_spec": {"supported_engines": ["api_ollama", "transformers", "api_openai"]}
        },
        "ocr_options": {"lang": ["en", "hi"]},
        "code_formula_options": {"model_spec": {"supported_engines": None}},
    }
    assert digest(first) == digest(second)
    assert first == original
    second["ocr_options"] = {"lang": ["hi", "en"]}
    assert digest(first) != digest(second)


@pytest.mark.parametrize("invalid", [["cpu", "cpu"], [1], "cpu", True])
def test_invalid_set_metadata_cannot_be_frozen(invalid: object) -> None:
    with pytest.raises(ValueError, match="duplicate-free"):
        canonical_pipeline_options({"supported_engines": invalid})
