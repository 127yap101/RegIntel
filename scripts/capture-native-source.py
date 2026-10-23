"""Capture every original native-text page offline; no authority or financial acceptance."""

import argparse
import importlib
import json
import socket
import sys
import time
from pathlib import Path
from typing import NoReturn, cast

from regintel.parsing.native_source import capture_native_source
from regintel.parsing.probe import ResourceModule

_NETWORK_ATTEMPTS: list[bool] = []


def _deny_network(*args: object, **kwargs: object) -> NoReturn:
    _NETWORK_ATTEMPTS.append(True)
    raise RuntimeError("Native source decoding cannot use network access.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        socket.socket.connect = _deny_network  # type: ignore[method-assign]
        socket.create_connection = _deny_network
        bank = capture_native_source(args.source, args.source_sha256, args.output_dir)
        if _NETWORK_ATTEMPTS:
            raise RuntimeError("Native source decoding attempted network access.")
        resource = cast(ResourceModule, importlib.import_module("resource"))
        print(
            json.dumps(
                {
                    "status": "COMPLETE_NATIVE_SOURCE_BANK",
                    "scope": bank.manifest.scope,
                    "source_sha256": bank.manifest.source_sha256,
                    "source_pages": bank.manifest.source_page_count,
                    "native_words": sum(page.word_count for page in bank.manifest.pages),
                    "native_bytes": sum(page.byte_size for page in bank.manifest.pages),
                    "manifest_sha256": bank.manifest.sha256,
                    "configuration_sha256": bank.manifest.configuration.configuration_sha256,
                    "seconds": time.perf_counter() - started,
                    "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "network_connect_attempts": len(_NETWORK_ATTEMPTS),
                    "acceptance_eligible": False,
                }
            ),
            flush=True,
        )
        return 0
    except Exception:
        print("Native source capture failed; raw diagnostics omitted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
