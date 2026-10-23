"""Complete native source-word banks with bounded page-wise decode and replay.

Native text decoding is distinct from layout, table prediction and OCR. Original
bottom-left corners stay unchanged. Selected contextual SDK captures can later
support a versioned evidence projection; this bank never accepts financial facts.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self, cast

from pydantic import Field, JsonValue, model_validator
from pypdf import PdfReader

from regintel.contracts.models import ContractModel, PageGeometry
from regintel.contracts.primitives import RawText, Sha256Hash
from regintel.parsing.configuration import _read_regular_file
from regintel.parsing.geometry import geometry_from_pdf_page
from regintel.parsing.models import PackageVersion, ReportedRectangle, package_manifest_sha256
from regintel.parsing.sdk import Dumpable, installed_packages

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_BANK_BYTES = 1024 * 1024 * 1024
PageIndex = Annotated[int, Field(strict=True, ge=0, le=1999)]
WordIndex = Annotated[int, Field(strict=True, ge=0, le=19999)]


def canonical_bytes(value: ContractModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def native_code_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class NativeSourceWord(ContractModel):
    index: WordIndex
    orig: Annotated[RawText, Field(max_length=20000)] | None
    text: Annotated[RawText, Field(max_length=20000)]
    from_ocr: Literal[False]
    raw_rectangle: ReportedRectangle

    @model_validator(mode="after")
    def declared_frame(self) -> Self:
        if self.raw_rectangle.coord_origin != "BOTTOMLEFT":
            raise ValueError("Native source words retain their declared bottom-left frame.")
        return self


class NativeSourcePage(ContractModel):
    schema_version: Literal["native-source-page-1"] = "native-source-page-1"
    source_sha256: Sha256Hash
    page_index: PageIndex
    page_geometry: PageGeometry
    raw_dimension: dict[str, JsonValue]
    words: Annotated[tuple[NativeSourceWord, ...], Field(strict=False, max_length=20000)]

    @model_validator(mode="after")
    def ordered_words(self) -> Self:
        if tuple(word.index for word in self.words) != tuple(range(len(self.words))):
            raise ValueError("Native words must retain the exact original ordered indices.")
        return self


class NativeSourceConfiguration(ContractModel):
    schema_version: Literal["native-source-configuration-1"] = "native-source-configuration-1"
    backend: Literal["DoclingPdfParser"] = "DoclingPdfParser"
    backend_version: Literal["7.22.1"] = "7.22.1"
    backend_code_sha256: Sha256Hash
    capture_code_sha256: Sha256Hash
    packages: Annotated[
        tuple[PackageVersion, ...], Field(strict=False, min_length=1, max_length=256)
    ]
    package_manifest_sha256: Sha256Hash
    boundary_type: Literal["CROP_BOX"] = "CROP_BOX"
    native_origin: Literal["BOTTOMLEFT"] = "BOTTOMLEFT"
    enforce_same_font: Literal[True] = True
    release_native_memory_every_n_pages: Literal[1] = 1
    materialize_words: Literal[True] = True
    materialize_lines: Literal[True] = True
    materialize_characters: Literal[False] = False
    decode_shapes: Literal[False] = False
    decode_bitmaps: Literal[False] = False
    include_bitmap_bytes: Literal[False] = False
    layout_enabled: Literal[False] = False
    ocr_enabled: Literal[False] = False

    @model_validator(mode="after")
    def package_identity(self) -> Self:
        if tuple(p.name for p in self.packages) != tuple(sorted({p.name for p in self.packages})):
            raise ValueError("Native package inventory must have unique ordered identities.")
        if package_manifest_sha256(self.packages) != self.package_manifest_sha256:
            raise ValueError("Native package inventory hash differs from its retained versions.")
        if not any(p.name == "docling-parse" and p.version == "7.22.1" for p in self.packages):
            raise ValueError("The native parser must retain the pinned backend version.")
        return self

    @property
    def configuration_sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class NativePageReceipt(ContractModel):
    page_index: PageIndex
    word_count: Annotated[int, Field(strict=True, ge=0, le=20000)]
    byte_size: Annotated[int, Field(strict=True, ge=1, le=MAX_PAGE_BYTES)]
    sha256: Sha256Hash


class NativeSourceManifest(ContractModel):
    schema_version: Literal["native-source-bank-1"] = "native-source-bank-1"
    scope: Literal["ALL_ORIGINAL_NATIVE_WORDS"] = "ALL_ORIGINAL_NATIVE_WORDS"
    source_sha256: Sha256Hash
    source_byte_size: Annotated[int, Field(strict=True, ge=1, le=MAX_SOURCE_BYTES)]
    source_page_count: Annotated[int, Field(strict=True, ge=1, le=2000)]
    configuration: NativeSourceConfiguration
    pages: Annotated[
        tuple[NativePageReceipt, ...], Field(strict=False, min_length=1, max_length=2000)
    ]
    acceptance_eligible: Literal[False] = False

    @model_validator(mode="after")
    def complete_source_coverage(self) -> Self:
        if tuple(p.page_index for p in self.pages) != tuple(range(self.source_page_count)):
            raise ValueError("A native bank must cover every original page once in order.")
        if sum(p.byte_size for p in self.pages) > MAX_BANK_BYTES:
            raise ValueError("The native bank exceeds its explicit total byte bound.")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


@dataclass(frozen=True)
class NativeSourceBank:
    directory: Path
    manifest: NativeSourceManifest

    def pages(self) -> Iterator[NativeSourcePage]:
        for receipt in self.manifest.pages:
            body = _read_regular_file(
                self.directory / f"page-{receipt.page_index:04}.json", MAX_PAGE_BYTES
            )
            if len(body) != receipt.byte_size or hashlib.sha256(body).hexdigest() != receipt.sha256:
                raise ValueError("Native page bytes differ from their sealed receipt.")
            page = NativeSourcePage.model_validate_json(body)
            if (
                canonical_bytes(page) != body
                or page.source_sha256 != self.manifest.source_sha256
                or page.page_index != receipt.page_index
                or len(page.words) != receipt.word_count
            ):
                raise ValueError("Native page membership differs from its complete source bank.")
            yield page


class NativePage(Protocol):
    dimension: Dumpable
    word_cells: list[Dumpable]


class NativeDocument(Protocol):
    def number_of_pages(self) -> int: ...
    def get_page(self, page_no: int) -> NativePage: ...
    def unload_pages(self, page_range: tuple[int, int]) -> None: ...
    def unload(self) -> bool: ...


class NativeParser(Protocol):
    def load(self, source: BytesIO, **kwargs: object) -> NativeDocument: ...


class Factory(Protocol):
    def __call__(self, **kwargs: object) -> object: ...


def _make_native_parser() -> tuple[NativeParser, object, object, NativeSourceConfiguration]:
    packages = installed_packages()
    module = importlib.import_module("docling_parse.pdf_parser")
    content = cast(Factory, module.ContentConfig)(
        char_cells_content_level=module.ContentLevel.COMPUTE,
        word_cells_content_level=module.ContentLevel.COMPUTE_AND_MATERIALIZE,
        line_cells_content_level=module.ContentLevel.COMPUTE_AND_MATERIALIZE,
        shapes_content_level=module.ContentLevel.SKIP,
        bitmaps_content_level=module.ContentLevel.SKIP,
        include_bitmap_bytes=False,
    )
    decode = cast(Factory, module.DecodeConfig)(
        enforce_same_font=True,
        release_native_memory_every_n_pages=1,
    )
    parser = cast(NativeParser, cast(Factory, module.DoclingPdfParser)(loglevel="fatal"))
    configuration = NativeSourceConfiguration(
        backend_code_sha256=hashlib.sha256(
            Path(cast(str, module.__file__)).read_bytes()
        ).hexdigest(),
        capture_code_sha256=native_code_sha256(),
        packages=packages,
        package_manifest_sha256=package_manifest_sha256(packages),
    )
    return parser, content, decode, configuration


def _source_bytes(source: Path, expected_sha256: str) -> tuple[bytes, PdfReader]:
    payload = _read_regular_file(source, MAX_SOURCE_BYTES)
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Native source bytes differ from their selected immutable identity.")
    reader = PdfReader(BytesIO(payload), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 2000:
        raise ValueError("Native source encryption or page limits are unsupported.")
    return payload, reader


def capture_native_source(source: Path, expected_sha256: str, output: Path) -> NativeSourceBank:
    """Decode every page from one verified in-memory snapshot; never rewrite a PDF."""
    payload, reader = _source_bytes(source, expected_sha256)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("A fresh explicit absolute native output directory is required.")
    parser, content, decode, configuration = _make_native_parser()
    output.mkdir(parents=True, exist_ok=False)
    document = parser.load(
        BytesIO(payload), lazy=True, content_config=content, decode_config=decode
    )
    receipts = []
    try:
        if document.number_of_pages() != len(reader.pages):
            raise ValueError("Native backend page count differs from the immutable PDF.")
        total = 0
        for index, original_page in enumerate(reader.pages):
            raw_page = document.get_page(index + 1)
            words = []
            if len(raw_page.word_cells) > 20000:
                raise ValueError("A native page exceeds the explicit word limit.")
            for value in raw_page.word_cells:
                raw = value.model_dump(mode="json")
                rect = raw.get("rect")
                if not isinstance(rect, dict):
                    raise ValueError("Native original word corners must be retained.")
                words.append(
                    NativeSourceWord.model_validate(
                        {
                            "index": raw.get("index"),
                            "orig": raw.get("orig"),
                            "text": raw.get("text"),
                            "from_ocr": raw.get("from_ocr"),
                            "raw_rectangle": rect | {"coordinate_frame": "DOCLING_PAGE"},
                        }
                    )
                )
            page = NativeSourcePage.model_validate(
                {
                    "source_sha256": expected_sha256,
                    "page_index": index,
                    "page_geometry": geometry_from_pdf_page(original_page),
                    "raw_dimension": raw_page.dimension.model_dump(mode="json"),
                    "words": words,
                }
            )
            encoded = canonical_bytes(page)
            total += len(encoded)
            if len(encoded) > MAX_PAGE_BYTES or total > MAX_BANK_BYTES:
                raise ValueError("Native source bytes exceed explicit page/bank limits.")
            with (output / f"page-{index:04}.json").open("xb") as handle:
                handle.write(encoded)
            receipts.append(
                NativePageReceipt(
                    page_index=index,
                    word_count=len(words),
                    byte_size=len(encoded),
                    sha256=hashlib.sha256(encoded).hexdigest(),
                )
            )
            document.unload_pages((index + 1, index + 2))
            del raw_page, page, words, encoded
    finally:
        document.unload()
    # A changed physical original cannot produce a successful bank even though
    # the conversion itself always used the already-verified immutable snapshot.
    _source_bytes(source, expected_sha256)
    manifest = NativeSourceManifest(
        source_sha256=expected_sha256,
        source_byte_size=len(payload),
        source_page_count=len(reader.pages),
        configuration=configuration,
        pages=tuple(receipts),
    )
    encoded_manifest = canonical_bytes(manifest)
    if len(encoded_manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("Native source manifest exceeds its explicit byte limit.")
    with (output / "manifest.json").open("xb") as handle:
        handle.write(encoded_manifest)
    return NativeSourceBank(output, manifest)


def read_native_source(source: Path, manifest_file: Path) -> NativeSourceBank:
    """Replay sealed bytes without installing or importing the optional parser SDK."""
    body = _read_regular_file(manifest_file, MAX_MANIFEST_BYTES)
    manifest = NativeSourceManifest.model_validate_json(body)
    if body != canonical_bytes(manifest):
        raise ValueError("Native source manifest must retain canonical unambiguous bytes.")
    payload, reader = _source_bytes(source, manifest.source_sha256)
    if len(payload) != manifest.source_byte_size or len(reader.pages) != manifest.source_page_count:
        raise ValueError("Native bank geometry/count differs from its physical original.")
    bank = NativeSourceBank(manifest_file.parent, manifest)
    for page, original in zip(bank.pages(), reader.pages, strict=True):
        if page.page_geometry != geometry_from_pdf_page(original):
            raise ValueError("Native source page geometry differs from the original PDF.")
    return bank
