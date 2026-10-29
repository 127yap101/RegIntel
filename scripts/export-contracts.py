"""Deterministic owned exporter for Pydantic wire schema and TypeScript types."""

import argparse
import json
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from regintel.contracts.models import (
    CONTRACT_VERSION,
    MODULE_OWNERSHIP,
    PUBLIC_MODELS,
    RELATION_DIRECTIONS,
)
from regintel.contracts.primitives import DATE_PATTERN, DECIMAL_PATTERN, ID_PATTERN

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def object_value(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError("Unsupported contract schema object.")
    return value


def sequence_value(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ValueError("Unsupported contract schema sequence.")
    return value


def ts_type(schema: JsonObject) -> str:
    """Fail closed on unsupported structure; runtime retains all constraints."""
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
            raise ValueError("Unsupported schema reference.")
        return reference.removeprefix("#/$defs/")
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(item) for item in sequence_value(schema["enum"]))
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            return " | ".join(
                ts_type(object_value(item)) for item in sequence_value(schema[keyword])
            )
    kind = schema.get("type")
    if kind == "string":
        brands = {
            ID_PATTERN: "CanonicalId",
            DECIMAL_PATTERN: "DecimalString",
            DATE_PATTERN: "DateString",
        }
        pattern = schema.get("pattern")
        return brands.get(pattern, "string") if isinstance(pattern, str) else "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        return f"ReadonlyArray<{ts_type(object_value(schema['items']))}>"
    if kind == "object":
        if schema.get("additionalProperties") is not False:
            raise ValueError("Shared objects must forbid unknown properties.")
        properties = object_value(schema.get("properties", {}))
        required = sequence_value(schema.get("required", []))
        fields = [
            f"readonly {json.dumps(name)}{'' if name in required else '?'}: "
            f"{ts_type(object_value(properties[name]))};"
            for name in sorted(properties)
        ]
        return "{ " + " ".join(fields) + " }"
    raise ValueError("Unsupported schema structure; extend exporter explicitly.")


def remove_openapi_annotations(value: JsonValue) -> None:
    """oneOf/kind consts validate unions; discriminator is an OpenAPI annotation."""
    if isinstance(value, dict):
        value.pop("discriminator", None)
        # Nested constraints on BeforeValidator-wrapped integer aliases can be
        # emitted under Pydantic's ge/le names. Preserve the stricter bound in
        # standard JSON Schema so strict browser validators enforce it too.
        for annotation, keyword in (("ge", "minimum"), ("le", "maximum")):
            if annotation in value and value.get("type") in ("integer", "number"):
                bound = value.pop(annotation)
                existing = value.get(keyword, bound)
                if (
                    isinstance(bound, bool)
                    or not isinstance(bound, (int, float))
                    or isinstance(existing, bool)
                    or not isinstance(existing, (int, float))
                ):
                    raise ValueError("An exported integer constraint requires numeric bounds.")
                value[keyword] = (
                    max(bound, existing) if annotation == "ge" else min(bound, existing)
                )
        for child in value.values():
            remove_openapi_annotations(child)
    elif isinstance(value, list):
        for child in value:
            remove_openapi_annotations(child)


def artifacts() -> dict[Path, str]:
    models: list[tuple[type[BaseModel], Literal["validation"]]] = [
        (model, "validation") for model in PUBLIC_MODELS.values()
    ]
    _, validation = models_json_schema(models)
    _, serialization = models_json_schema(
        [(model, "serialization") for model in PUBLIC_MODELS.values()]
    )
    if validation != serialization:
        raise ValueError("Validation and serialization wire schemas diverged.")
    schema = cast(JsonObject, validation)
    remove_openapi_annotations(schema)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://regintel.local/contracts/{CONTRACT_VERSION}"
    schema["title"] = "RegIntel shared wire contracts"
    definitions = object_value(schema["$defs"])
    names = sorted(PUBLIC_MODELS)
    declarations = [
        "// Generated by scripts/export-contracts.py. Edit the Python contracts instead.",
        "export type CanonicalId = string & { readonly __canonicalId: unique symbol };",
        "export type DecimalString = string & { readonly __decimalString: unique symbol };",
        "export type DateString = string & { readonly __dateString: unique symbol };",
        f"export const CONTRACT_VERSION = {json.dumps(CONTRACT_VERSION)} as const;",
        "export const CONTRACT_NAMES = " + json.dumps(names) + " as const;",
        "export type ContractName = typeof CONTRACT_NAMES[number];",
        "export const RELATION_DIRECTIONS = "
        + json.dumps(RELATION_DIRECTIONS, sort_keys=True)
        + " as const;",
        "export const MODULE_OWNERSHIP = "
        + json.dumps(MODULE_OWNERSHIP, sort_keys=True)
        + " as const;",
    ]
    for name in sorted(definitions):
        declarations.append(f"export type {name} = {ts_type(object_value(definitions[name]))};")
    declarations.append(
        "export interface ContractTypes { "
        + " ".join(f"readonly {name}: {name};" for name in names)
        + " }"
    )
    root = Path(__file__).resolve().parents[1]
    return {
        root / "frontend/src/contracts/schema.json": json.dumps(schema, indent=2, sort_keys=True)
        + "\n",
        root / "frontend/src/contracts/generated.ts": "\n".join(declarations) + "\n",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report drift without writing files.")
    options = parser.parse_args()
    for path, content in artifacts().items():
        expected = content.encode("utf-8")
        if options.check:
            if not path.is_file() or path.read_bytes() != expected:
                print(f"Contract artifact differs: {path.name}; run scripts/export-contracts.py.")
                return 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
    print(
        "Shared contract artifacts match."
        if options.check
        else "Shared contract artifacts generated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
