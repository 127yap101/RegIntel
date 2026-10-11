"""Controlled offline converter probe; no database writes or acceptance."""

import argparse
import hashlib
import importlib
import json
import socket
import time
from pathlib import Path
from typing import NoReturn, Protocol, cast

from regintel.parsing.sdk import capture_conversion, create_converter

_NETWORK_ATTEMPTS: list[bool] = []


class ResourceUsage(Protocol):
    ru_maxrss: int


class ResourceModule(Protocol):
    RUSAGE_SELF: int

    def getrusage(self, target: int) -> ResourceUsage: ...


def _deny_network(*args: object, **kwargs: object) -> NoReturn:
    _NETWORK_ATTEMPTS.append(True)
    raise RuntimeError("The offline conversion probe attempted network access")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    source: Path = arguments.source
    output: Path = arguments.output
    if not source.is_absolute() or not source.is_file() or source.is_symlink():
        raise ValueError("An existing application-owned absolute source path is required")
    if not output.is_absolute() or output.exists():
        raise ValueError("A fresh absolute probe output is required")
    socket.socket.connect = _deny_network  # type: ignore[method-assign]
    socket.create_connection = _deny_network
    start = time.perf_counter()
    converter, configuration = create_converter(arguments.models)
    initialized = time.perf_counter()
    captured = capture_conversion(converter, source)
    if _NETWORK_ATTEMPTS:
        raise RuntimeError("Conversion attempted a forbidden network request")
    finished = time.perf_counter()
    captured["configuration"] = configuration
    captured["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(captured, handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
    resource_module = cast(ResourceModule, importlib.import_module("resource"))
    print(
        json.dumps(
            {
                "status": captured["status"],
                "initialization_seconds": initialized - start,
                "conversion_seconds": finished - initialized,
                "max_rss_kib": resource_module.getrusage(resource_module.RUSAGE_SELF).ru_maxrss,
                "network_attempts": len(_NETWORK_ATTEMPTS),
                "network_disabled": True,
                "output_bytes": output.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
