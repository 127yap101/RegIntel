"""Benchmark one complete original offline; never upload, persist evidence or publish."""

import argparse
import hashlib
import importlib
import json
import os
import socket
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, cast

from pypdf import PdfReader

from regintel.parsing.configuration import load_runtime_configuration
from regintel.parsing.full_filing import (
    complete_page_coverage,
    create_full_filing_converter,
    json_bytes,
    write_capture,
)
from regintel.parsing.probe import ResourceModule
from regintel.parsing.sdk import capture_conversion

_NETWORK_ATTEMPTS: list[bool] = []


def _deny_network(*args: object, **kwargs: object) -> NoReturn:
    _NETWORK_ATTEMPTS.append(True)
    raise RuntimeError("The whole-filing benchmark forbids network access.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--baseline-config", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output: Path = args.output_dir
    created = False
    report: dict[str, object] = {"status": "FAILED", "acceptance_eligible": False}
    started = time.perf_counter()
    try:
        if not output.is_absolute() or output.exists() or output.is_symlink():
            raise ValueError("A fresh absolute output folder is required.")
        source: Path = args.source
        baseline = load_runtime_configuration(args.baseline_config)
        if (
            not source.is_absolute()
            or source.is_symlink()
            or not source.is_file()
            or not 0 < source.stat().st_size <= baseline.source_limits.max_file_bytes
        ):
            raise ValueError("An existing bounded original PDF is required.")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if source_hash != args.source_sha256:
            raise ValueError("Original bytes differ from the explicitly selected source hash.")
        reader = PdfReader(source, strict=True)
        source_pages = len(reader.pages)
        if reader.is_encrypted or not 1 <= source_pages <= baseline.source_limits.max_pages:
            raise ValueError("The original violates the selected page/encryption bounds.")
        if not args.models.is_absolute():
            raise ValueError("An explicit absolute existing model root is required.")
        output.mkdir(parents=True, exist_ok=False)
        created = True
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        socket.socket.connect = _deny_network  # type: ignore[method-assign]
        socket.create_connection = _deny_network
        converter, resolved, profile = create_full_filing_converter(
            args.models, baseline, timeout_seconds=args.timeout_seconds
        )
        (output / "profile.json").write_bytes(json_bytes(profile))
        (output / "configuration.json").write_bytes(json_bytes(resolved))
        initialized = time.perf_counter()
        print(
            json.dumps({"event": "INITIALIZED", "source_pages": source_pages}),
            flush=True,
        )
        captured = capture_conversion(converter, source)
        finished = time.perf_counter()
        if _NETWORK_ATTEMPTS or hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
            raise ValueError("Offline/source invariants failed during conversion.")
        captured["source_sha256"] = source_hash
        captured["configuration"] = resolved
        size, capture_hash = write_capture(output / "raw.json", captured)
        complete = complete_page_coverage(captured, source_pages)
        resource = cast(ResourceModule, importlib.import_module("resource"))
        pages = cast(list[dict[str, object]], captured["pages"])
        cells = sum(len(cast(list[object], page["cells"])) for page in pages)
        report = {
            "version": "full-filing-benchmark-1",
            "checked_at_utc": datetime.now(UTC).isoformat(),
            "status": "COMPLETE_SDK_CAPTURE" if complete else "INCOMPLETE_SDK_CAPTURE",
            "source_sha256": source_hash,
            "source_pages": source_pages,
            "requested_pages": "ALL_ORIGINAL_PAGES",
            "sdk_status": captured["status"],
            "sdk_error_count": len(cast(list[object], captured["errors"])),
            "result_page_count": len(pages),
            "processed_page_count": sum(bool(page["cells"]) for page in pages),
            "result_cells": cells,
            "raw_capture_bytes": size,
            "raw_capture_sha256": capture_hash,
            "experiment_sha256": profile["experiment_sha256"],
            "sdk_configuration_sha256": resolved["configuration_sha256"],
            "initialization_seconds": initialized - started,
            "conversion_seconds": finished - initialized,
            "capture_serialization_seconds": time.perf_counter() - finished,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "network_connect_attempts": len(_NETWORK_ATTEMPTS),
            "m1_artifact_created": False,
            "evidence_persisted": False,
            "acceptance_eligible": False,
            "accepted_facts": 0,
        }
        (output / "report.json").write_bytes(json_bytes(report) + b"\n")
        print(json.dumps(report), flush=True)
        return 0 if complete else 2
    except Exception:
        # SDK/PDF failures can include untrusted filing text. Keep the public diagnostic fixed.
        if created and not (output / "report.json").exists():
            report["total_seconds"] = time.perf_counter() - started
            (output / "report.json").write_bytes(json_bytes(report) + b"\n")
        print("Whole-filing benchmark failed; raw diagnostics omitted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
