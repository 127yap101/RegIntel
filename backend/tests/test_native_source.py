"""Authored blank-PDF/native declarations test engineering integrity, not OCR accuracy."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter

from regintel.parsing import native_source as native
from regintel.parsing.models import PackageVersion, package_manifest_sha256


class Dump:
    def __init__(self, value):
        self.value = value

    def model_dump(self, *, mode):
        return self.value


def configuration():
    packages = (PackageVersion(name="docling-parse", version="7.22.1"),)
    return native.NativeSourceConfiguration(
        backend_code_sha256="a" * 64,
        capture_code_sha256=native.native_code_sha256(),
        packages=packages,
        package_manifest_sha256=package_manifest_sha256(packages),
    )


def word(index=0, *, orig="₹😀", origin="BOTTOMLEFT", from_ocr=False):
    return {
        "index": index,
        "orig": orig,
        "text": orig,
        "from_ocr": from_ocr,
        "rect": {
            "r_x0": 20.0,
            "r_y0": 30.0,
            "r_x1": 40.0,
            "r_y1": 30.0,
            "r_x2": 40.0,
            "r_y2": 45.0,
            "r_x3": 20.0,
            "r_y3": 45.0,
            "coord_origin": origin,
        },
    }


def prepared(tmp_path, monkeypatch, *, page_count=2, words=None):
    source = tmp_path / "original.pdf"
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=612, height=792)
    writer.write(source)
    payload = source.read_bytes()
    events = []
    declared = [word()] if words is None else words

    class Document:
        def number_of_pages(self):
            return page_count

        def get_page(self, number):
            events.append(("get", number))
            return SimpleNamespace(
                dimension=Dump({"rect": {"width": 612.0, "height": 792.0}}),
                word_cells=[Dump(item) for item in declared],
            )

        def unload_pages(self, interval):
            events.append(("release", interval))

        def unload(self):
            events.append(("unload",))
            return True

    document = Document()

    class Parser:
        def load(self, stream, **kwargs):
            assert stream.read() == payload and kwargs["lazy"] is True
            events.append(("load",))
            return document

    monkeypatch.setattr(
        native, "_make_native_parser", lambda: (Parser(), object(), object(), configuration())
    )
    return source, hashlib.sha256(payload).hexdigest(), tmp_path / "fresh", events, document


def test_every_page_decodes_once_releases_immediately_and_replays_exactly(tmp_path, monkeypatch):
    source, sha, output, events, _ = prepared(tmp_path, monkeypatch)
    bank = native.capture_native_source(source, sha, output)
    assert events == [
        ("load",),
        ("get", 1),
        ("release", (1, 2)),
        ("get", 2),
        ("release", (2, 3)),
        ("unload",),
    ]
    assert bank.manifest.scope == "ALL_ORIGINAL_NATIVE_WORDS"
    assert bank.manifest.acceptance_eligible is False
    assert bank.manifest.configuration.ocr_enabled is False
    assert bank.manifest.configuration.layout_enabled is False
    assert [page.words[0].orig for page in bank.pages()] == ["₹😀", "₹😀"]
    replay = native.read_native_source(source, output / "manifest.json")
    assert replay.manifest == bank.manifest
    assert list(replay.pages()) == list(bank.pages())
    assert all(page.words[0].raw_rectangle.coord_origin == "BOTTOMLEFT" for page in replay.pages())


def test_blank_native_page_is_retained_without_fabricated_zero_or_ocr(tmp_path, monkeypatch):
    source, sha, output, _, _ = prepared(tmp_path, monkeypatch, words=[])
    bank = native.capture_native_source(source, sha, output)
    assert len(bank.manifest.pages) == 2
    assert all(receipt.word_count == 0 for receipt in bank.manifest.pages)
    assert all(page.words == () for page in bank.pages())


@pytest.mark.parametrize(
    "change", ["ocr", "unknown_origin", "index_gap", "too_many", "wrong_pages"]
)
def test_native_failures_never_write_a_complete_manifest(tmp_path, monkeypatch, change):
    declared = [word()]
    pages = 2
    if change == "ocr":
        declared = [word(from_ocr=True)]
    elif change == "unknown_origin":
        declared = [word(origin="TOPLEFT")]
    elif change == "index_gap":
        declared = [word(index=1)]
    elif change == "too_many":
        declared *= 20001
    else:
        pages = 1
    source, sha, output, events, _ = prepared(
        tmp_path, monkeypatch, page_count=pages, words=declared
    )
    with pytest.raises((ValueError, ValidationError)):
        native.capture_native_source(source, sha, output)
    assert not (output / "manifest.json").exists()
    assert events[-1] == ("unload",)


def test_source_replacement_during_decode_cannot_change_the_private_snapshot(tmp_path, monkeypatch):
    source, sha, output, events, document = prepared(tmp_path, monkeypatch)
    get_page = document.get_page

    def changed(number):
        source.write_bytes(b"replaced physical source")
        return get_page(number)

    monkeypatch.setattr(document, "get_page", changed)
    with pytest.raises(ValueError, match="immutable"):
        native.capture_native_source(source, sha, output)
    assert events[-1] == ("unload",)
    assert not (output / "manifest.json").exists()


def test_existing_output_and_wrong_hash_never_initialize_sdk(tmp_path, monkeypatch):
    source, sha, output, _, _ = prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(native, "_make_native_parser", lambda: pytest.fail("No SDK expected"))
    output.mkdir()
    marker = output / "keep.bin"
    marker.write_bytes(b"keep")
    with pytest.raises(ValueError, match="fresh"):
        native.capture_native_source(source, sha, output)
    assert list(output.iterdir()) == [marker]
    with pytest.raises(ValueError, match="immutable"):
        native.capture_native_source(source, "0" * 64, tmp_path / "different")


def test_byte_bounds_fail_before_a_manifest_can_claim_completeness(tmp_path, monkeypatch):
    source, sha, output, events, _ = prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(native, "MAX_PAGE_BYTES", 20)
    with pytest.raises(ValueError, match="limits"):
        native.capture_native_source(source, sha, output)
    assert events[-1] == ("unload",)
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize(
    "change", ["page_hash", "page_bytes", "source", "geometry", "duplicate_keys"]
)
def test_replay_rejects_tampered_membership_and_even_rehashed_noncanonical_bytes(
    tmp_path, monkeypatch, change
):
    source, sha, output, _, _ = prepared(tmp_path, monkeypatch)
    native.capture_native_source(source, sha, output)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    page_path = output / "page-0000.json"
    if change == "source":
        source.write_bytes(b"different original")
    elif change == "page_hash":
        page_path.write_bytes(b"changed")
    elif change == "page_bytes":
        manifest["pages"][0]["byte_size"] += 1
    else:
        page = json.loads(page_path.read_bytes())
        if change == "geometry":
            page["page_geometry"]["rotation"] = 180
            body = json.dumps(
                page, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        else:
            body = page_path.read_bytes().replace(
                b'{"page_geometry":', b'{"page_index":99,"page_geometry":', 1
            )
        page_path.write_bytes(body)
        manifest["pages"][0]["sha256"] = hashlib.sha256(body).hexdigest()
        manifest["pages"][0]["byte_size"] = len(body)
    manifest_path.write_bytes(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    )
    with pytest.raises(ValueError):
        native.read_native_source(source, manifest_path)


@pytest.mark.parametrize(
    "change", ["missing_page", "out_of_order", "boolean_index", "false_count", "extra_field"]
)
def test_manifest_cannot_relabel_sparse_or_reordered_pages_as_complete(
    tmp_path, monkeypatch, change
):
    source, sha, output, _, _ = prepared(tmp_path, monkeypatch)
    bank = native.capture_native_source(source, sha, output)
    value = bank.manifest.model_dump(mode="json")
    if change == "missing_page":
        value["pages"].pop()
    elif change == "out_of_order":
        value["pages"].reverse()
    elif change == "boolean_index":
        value["pages"][0]["page_index"] = False
    elif change == "false_count":
        value["source_page_count"] = 1
    else:
        value["pretend_accepted"] = True
    with pytest.raises(ValidationError):
        native.NativeSourceManifest.model_validate(value)


def test_noncanonical_manifest_is_rejected_even_when_it_has_the_same_values(tmp_path, monkeypatch):
    source, sha, output, _, _ = prepared(tmp_path, monkeypatch)
    native.capture_native_source(source, sha, output)
    path = output / "manifest.json"
    path.write_bytes(b" " + path.read_bytes())
    with pytest.raises(ValueError, match="canonical"):
        native.read_native_source(source, path)
