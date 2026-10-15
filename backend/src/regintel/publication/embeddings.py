"""Pinned local CPU inference and exact tokenizer-bounded source chunks."""

import hashlib
import importlib.metadata
import json
import math
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal, Protocol, cast

from pydantic import Field, model_validator

from regintel.candidates.models import SourceSpan
from regintel.candidates.records import stable_id
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, SafeInteger, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.publication.models import CorpusManifest

REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
MODEL_FILES = {
    "onnx/model.onnx": (
        133093490,
        "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35",
        "sha256",
    ),
    "tokenizer.json": (711396, "688882a79f44442ddc1f60d70334a7ff5df0fb47", "git-blob"),
    "config.json": (743, "3992bf890728a92476c700e6e657fd696eb94160", "git-blob"),
    "1_Pooling/config.json": (190, "1da070f0993788c8851a652170ff013aa54dd519", "git-blob"),
    "sentence_bert_config.json": (52, "ea85692bff64b0d1917833c31ddbca8ab10f5455", "git-blob"),
}


def verify_model_file(name: str, contents: bytes) -> str:
    if name not in MODEL_FILES:
        raise ValueError("Only the pinned embedding file allowlist can be read.")
    size, expected, algorithm = MODEL_FILES[name]
    digest = (
        hashlib.sha256(contents).hexdigest()
        if algorithm == "sha256"
        else hashlib.sha1(b"blob " + str(len(contents)).encode() + b"\0" + contents).hexdigest()
    )
    if len(contents) != size or digest != expected:
        raise ValueError("A pinned embedding artifact fingerprint differs.")
    return hashlib.sha256(contents).hexdigest()


def model_manifest(root: Path) -> dict[str, object]:
    files: dict[str, str] = {}
    for name in sorted(MODEL_FILES):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Embedding files must remain in the selected local model root.")
        with path.open("rb") as stream:
            contents = stream.read(MODEL_FILES[name][0] + 1)
        files[name] = verify_model_file(name, contents)
    return {
        "model": "BAAI/bge-small-en-v1.5",
        "revision": REVISION,
        "license": "MIT",
        "files": files,
    }


def manifest_sha256(root: Path) -> str:
    return hashlib.sha256(
        json.dumps(model_manifest(root), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class TextEncoder(Protocol):
    def token_count(self, text: str) -> int: ...
    def embed(self, text: str) -> tuple[float, ...]: ...


class CpuBgeEncoder:
    """No network, truncation, remote Python code or authoritative numeric arithmetic."""

    def __init__(self, root: Path, expected_manifest_sha256: str) -> None:
        if manifest_sha256(root) != expected_manifest_sha256:
            raise ValueError("Embedding model manifest differs from the approved configuration.")
        for package, version in (("onnxruntime", "1.30.0"), ("tokenizers", "0.23.2")):
            if importlib.metadata.version(package) != version:
                raise ValueError("The installed CPU embedding runtime version differs.")
        import onnxruntime as ort  # type: ignore[import-untyped]
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(root / "onnx/model.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        pooling = json.loads((root / "1_Pooling/config.json").read_text(encoding="utf-8"))
        if (
            config.get("hidden_size") != 384
            or config.get("max_position_embeddings") != 512
            or pooling.get("pooling_mode_cls_token") is not True
            or pooling.get("pooling_mode_mean_tokens") is not False
        ):
            raise ValueError("The pinned model must provide 384-dimensional CLS embeddings.")

    def token_count(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=True).ids)

    def embed(self, text: str) -> tuple[float, ...]:
        import numpy as np
        from numpy.typing import NDArray

        encoded = self.tokenizer.encode(text, add_special_tokens=True)
        if not text.strip() or not 2 < len(encoded.ids) <= 512:
            raise ValueError("Embedding input is empty or exceeds the actual tokenizer limit.")
        feeds = {
            "input_ids": np.asarray([encoded.ids], dtype=np.int64),
            "attention_mask": np.asarray([encoded.attention_mask], dtype=np.int64),
            "token_type_ids": np.asarray([encoded.type_ids], dtype=np.int64),
        }
        result = self.session.run(None, feeds)
        hidden = cast(NDArray[np.float32], result[0])
        cls = hidden[0, 0, :].astype(np.float64)
        norm = float(np.linalg.norm(cls))
        if (
            cls.shape != (384,)
            or not np.isfinite(cls).all()
            or not math.isfinite(norm)
            or norm <= 0
        ):
            raise ValueError("The local model returned an invalid embedding.")
        return tuple(float(value) for value in cls / norm)


class SourceChunk(ContractModel):
    id: CanonicalId
    observation_id: CanonicalId
    support: SourceSpan
    token_count: Annotated[SafeInteger, Field(ge=3, le=512)]
    embedding: Annotated[tuple[float, ...], Field(strict=False, min_length=384, max_length=384)]
    term_counts: dict[str, Annotated[SafeInteger, Field(ge=1)]]

    @model_validator(mode="after")
    def finite_normalized(self) -> "SourceChunk":
        if (
            not all(math.isfinite(value) for value in self.embedding)
            or abs(math.sqrt(sum(value * value for value in self.embedding)) - 1.0) > 1e-5
        ):
            raise ValueError("Embedding vectors must be finite and L2 normalized.")
        if self.term_counts != lexical_counts(self.support.quote):
            raise ValueError("Lexical postings must describe the same exact chunk.")
        return self


def lexical_counts(text: str) -> dict[str, int]:
    return dict(sorted(Counter(re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)).items()))


def split_support(span: SourceSpan, count: Callable[[str], int]) -> tuple[SourceSpan, ...]:
    """Split on Unicode character offsets with actual token checks, without dropping text."""
    result: list[SourceSpan] = []
    offset = 0
    while offset < len(span.quote):
        text = span.quote[offset:]
        length = len(text)
        if count(text) > 450:
            lower, upper = 1, length
            while lower < upper:
                middle = (lower + upper + 1) // 2
                if count(text[:middle]) <= 450:
                    lower = middle
                else:
                    upper = middle - 1
            length = lower
            while length > 1 and count(text[:length]) > 450:
                length -= 1
            boundary = text.rfind(" ", length // 2, length)
            if boundary >= 0:
                length = boundary + 1
        piece = text[:length]
        if count(piece) > 512 or not piece:
            raise ValueError("Source text cannot be encoded within the model token limit.")
        result.append(
            SourceSpan(
                evidence_id=span.evidence_id,
                start=span.start + offset,
                end=span.start + offset + length,
                quote=piece,
            )
        )
        offset += length
    return tuple(result)


class RetrievalProjection(ContractModel):
    version: Literal["1.0.0"] = "1.0.0"
    corpus_version_id: CanonicalId
    manifest_sha256: Sha256Hash
    embedding_manifest_sha256: Sha256Hash
    chunks: Annotated[tuple[SourceChunk, ...], Field(strict=False, max_length=100000)]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def project_retrieval(manifest: CorpusManifest, encoder: TextEncoder) -> RetrievalProjection:
    chunks: list[SourceChunk] = []
    # Retain historical evidence for explicit history/as-of filtering. Consumers must
    # join the requested corpus's approved active/as-of view before ranking.
    for observation in manifest.observations:
        seen: set[SourceSpan] = set()
        sources = list(observation.supports)
        for witness in observation.context_supports:
            if not any(
                s.evidence_id == witness.span.evidence_id
                and s.start <= witness.span.start < witness.span.end <= s.end
                for s in sources
            ):
                sources.append(witness.span)
        for support in sources:
            if support in seen:
                continue
            seen.add(support)
            for piece in split_support(support, encoder.token_count):
                if not piece.quote.strip():
                    continue
                chunks.append(
                    SourceChunk(
                        id=stable_id(
                            "chunk:"
                            + manifest.id
                            + ":"
                            + observation.id
                            + ":"
                            + piece.evidence_id
                            + f":{piece.start}:{piece.end}"
                        ),
                        observation_id=observation.id,
                        support=piece,
                        token_count=encoder.token_count(piece.quote),
                        embedding=encoder.embed(piece.quote),
                        term_counts=lexical_counts(piece.quote),
                    )
                )
    return RetrievalProjection(
        corpus_version_id=manifest.id,
        manifest_sha256=manifest.sha256,
        embedding_manifest_sha256=manifest.configuration.embedding_manifest_sha256,
        chunks=tuple(sorted(chunks, key=lambda item: item.id)),
    )
