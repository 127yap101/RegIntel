"""Prepare one original PDF page offline; never upload, accept or publish facts."""

import argparse
import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import NoReturn, Protocol, cast

from regintel.numerical.source_pages import (
    FRAME,
    MAX_CAPTURE_BYTES,
    build_page_capture,
    capture_bytes,
)
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.parsing.sdk import SdkResult, create_converter

_NETWORK_ATTEMPTS: list[bool] = []


class PageConverter(Protocol):
    def convert(
        self,
        source: Path,
        *,
        page_range: tuple[int, int],
        max_num_pages: int,
        max_file_size: int,
        raises_on_error: bool,
    ) -> SdkResult: ...


def _deny_network(*args: object, **kwargs: object) -> NoReturn:
    _NETWORK_ATTEMPTS.append(True)
    raise RuntimeError("The numerical page probe cannot use network access.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--pdf-page", type=int, required=True, help="One-based original PDF page.")
    parser.add_argument("--parser-config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--models", type=Path, help="Existing pinned models in the Linux parser image."
    )
    mode.add_argument("--replay", type=Path, help="Recheck a bounded retained raw SDK capture.")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Fresh absolute output folder."
    )
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        source: Path = args.source
        output: Path = args.output_dir
        if not output.is_absolute() or output.exists() or output.is_symlink():
            raise ValueError("A fresh explicit absolute output folder is required.")
        if not 1 <= args.pdf_page <= 2_000:
            raise ValueError("Select one bounded original PDF page.")
        settings = ParserRuntimeConfiguration.model_validate_json(args.parser_config.read_bytes())
        if settings.coordinate_frame != FRAME.value:
            raise ValueError("The preparation tool requires its explicitly calibrated SDK frame.")
        if args.replay is not None:
            with args.replay.open("rb") as handle:
                raw_bytes = handle.read(MAX_CAPTURE_BYTES + 1)
            if len(raw_bytes) > MAX_CAPTURE_BYTES:
                raise ValueError("The raw SDK capture exceeds the explicit byte bound.")
            captured: object = json.loads(raw_bytes)
        else:
            if (
                not source.is_absolute()
                or source.is_symlink()
                or not source.is_file()
                or source.stat().st_size > settings.source_limits.max_file_bytes
            ):
                raise ValueError("An existing bounded original source is required.")
            if hashlib.sha256(source.read_bytes()).hexdigest() != args.source_sha256:
                raise ValueError("Original source bytes differ from the selected hash.")
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            socket.socket.connect = _deny_network  # type: ignore[method-assign]
            socket.create_connection = _deny_network
            converter, config = create_converter(args.models)
            if config["configuration_sha256"] != settings.sdk_configuration_sha256:
                raise ValueError(
                    "The installed parser differs from the selected SDK configuration."
                )
            result = cast(PageConverter, converter).convert(
                source,
                page_range=(args.pdf_page, args.pdf_page),
                max_num_pages=settings.source_limits.max_pages,
                max_file_size=settings.source_limits.max_file_bytes,
                raises_on_error=False,
            )
            captured = {
                "status": getattr(result.status, "value", None),
                "document": result.document.export_to_dict(),
                "pages": [
                    {
                        "page_no": page.page_no,
                        "parsed_page": page.parsed_page.model_dump(mode="json")
                        if page.parsed_page is not None
                        else None,
                        "cells": [cell.model_dump(mode="json") for cell in page.cells],
                    }
                    for page in result.pages
                ],
                "errors": [error.model_dump(mode="json") for error in result.errors],
                "original_source_sha256": args.source_sha256,
                "requested_original_pdf_page": args.pdf_page,
                "configuration": config,
            }
            if _NETWORK_ATTEMPTS:
                raise RuntimeError("The offline numerical page probe attempted network access.")
        prepared = build_page_capture(
            captured,
            source=source,
            pdf_page=args.pdf_page,
            expected_source_sha256=args.source_sha256,
            expected_sdk_configuration_sha256=settings.sdk_configuration_sha256,
        )
        # Detect a source replacement during conversion/preparation before writing results.
        if hashlib.sha256(source.read_bytes()).hexdigest() != args.source_sha256:
            raise ValueError("The original source changed during preparation.")
        raw_output = json.dumps(
            captured,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        prepared_output = capture_bytes(prepared)
        report = {
            "status": "PREPARATION_ONLY",
            "mode": "REPLAY" if args.replay is not None else "OFFLINE_LINUX_SDK",
            "source_sha256": prepared.source_sha256,
            "source_page_count": prepared.source_page_count,
            "page_index": prepared.page_index,
            "sdk_configuration_sha256": prepared.sdk_configuration_sha256,
            "preparation_code_sha256": prepared.preparation_code_sha256,
            "raw_capture_sha256": prepared.raw_capture_sha256,
            "prepared_sha256": hashlib.sha256(prepared_output).hexdigest(),
            "native_words": sum(word.from_ocr is False for word in prepared.words),
            "preview_cells": len(prepared.cells),
            "proposed_word_mappings": sum(item.state == "PROPOSED" for item in prepared.mappings),
            "acceptance_eligible": False,
            "seconds": time.perf_counter() - started,
            "limitation": "Membership proposals need original-source and joint context checks; "
            "this is not a complete parse, accepted evidence, financial fact or M2 input.",
        }
        output.mkdir(parents=True, exist_ok=False)
        (output / "raw.json").write_bytes(raw_output)
        (output / "prepared.json").write_bytes(prepared_output)
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
        return 0
    except Exception:
        # SDK/PDF/validation exceptions may contain source text, paths or credentials.
        print("Numerical page preparation failed; diagnostics omitted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
