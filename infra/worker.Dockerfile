FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/backend
# OpenCV's required Debian libraries and their complete APT dependency closure.
# Acquire with scripts/acquire-worker-libs.py; exact versions/hashes/licenses are
# frozen in data/worker-runtime-libs.json. Installation is offline and container-only.
COPY .cache/worker-debs /tmp/worker-debs
RUN --network=none cd /tmp/worker-debs && \
    printf '%s  SHA256SUMS\n' '6b889dadc5247b656177fc61d41cb7af80c75a68f8db8d1b709c23fedd11c803' | sha256sum -c - && \
    python -c "from pathlib import Path; expected = {line.split()[1] for line in Path('SHA256SUMS').read_text().splitlines() if line.split()[1].endswith('.deb')}; assert {path.name for path in Path('.').glob('*.deb')} == expected, 'unlisted Debian archive input'" && \
    gpgv --keyring /usr/share/keyrings/debian-archive-keyring.gpg bookworm.InRelease && \
    sha256sum --check --strict SHA256SUMS && \
    awk '$2 ~ /\.deb$/ {print $2}' SHA256SUMS | xargs --no-run-if-empty dpkg -i -- && \
    dpkg --audit && rm -rf /tmp/worker-debs
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,id=regintel-worker-uv,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --extra parsing --no-install-project && \
    groupadd --gid 10001 regintel && useradd --uid 10001 --gid 10001 --no-create-home regintel
RUN --mount=type=cache,id=regintel-worker-uv,target=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/app/backend/.stages-venv \
    uv sync --locked --no-dev --no-editable --extra entities --no-install-project
COPY backend/src ./src
RUN --mount=type=cache,id=regintel-worker-uv,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --extra parsing
RUN --mount=type=cache,id=regintel-worker-uv,target=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/app/backend/.stages-venv \
    uv sync --locked --no-dev --no-editable --extra entities
USER 10001:10001
ENV PATH="/app/backend/.venv/bin:$PATH" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN --network=none python -c "import cv2, scipy, rapidocr, torch, torchvision; from docling.document_converter import DocumentConverter; assert torch.version.cuda is None"
RUN --network=none /app/backend/.stages-venv/bin/python -c "import spacy, rapidfuzz; from regintel.processing.processor import Processor; assert spacy.__version__ == '3.8.16'; assert rapidfuzz.__version__ == '3.14.6'"
CMD ["celery", "--app=regintel.ingestion.worker:app", "worker", "--loglevel=WARNING", "--concurrency=1", "--hostname=ingestion@regintel", "--without-gossip", "--without-mingle"]
