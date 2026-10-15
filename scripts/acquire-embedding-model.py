"""Acquire only immutable allowlisted BGE assets; no model code or credentials."""

import argparse
import json
import os
import tempfile
import urllib.request
from pathlib import Path

from regintel.publication.embeddings import MODEL_FILES, REVISION, model_manifest, verify_model_file

ROOT = Path(__file__).resolve().parents[1]


def acquire(root: Path) -> dict[str, object]:
    if root.is_symlink() or not root.resolve().is_relative_to(ROOT.resolve() / "models"):
        raise ValueError("The embedding target must be inside the project's ignored models root.")
    for name, (size, _, _) in MODEL_FILES.items():
        target = root / name
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("A model target escapes the selected project directory.")
        if target.is_file():
            verify_model_file(name, target.read_bytes())
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/{REVISION}/{name}"
        request = urllib.request.Request(
            url, headers={"User-Agent": "RegIntel-model-acquisition/1.0"}
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            contents = response.read(size + 1)
        verify_model_file(name, contents)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            stream.write(contents)
            temporary = Path(stream.name)
        os.replace(temporary, target)
    return model_manifest(root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "models/bge-small-en-v1.5")
    args = parser.parse_args()
    try:
        manifest = acquire(args.root)
        print(json.dumps(manifest, sort_keys=True, indent=2))
    except (OSError, ValueError):
        raise SystemExit("Pinned embedding acquisition failed; details omitted.") from None


if __name__ == "__main__":
    main()
