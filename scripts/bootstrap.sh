#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export UV_CACHE_DIR="$repo_root/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$repo_root/.tools/python"
export PLAYWRIGHT_BROWSERS_PATH="$repo_root/.cache/ms-playwright"
uv_version=0.12.23
python_version=3.12.14
if [[ -x "$repo_root/.tools/uv/uv" ]]; then
  uv_bin="$repo_root/.tools/uv/uv"
elif command -v uv >/dev/null 2>&1; then
  uv_bin="$(command -v uv)"
else
  echo "Install checksum-verified uv $uv_version into .tools/uv or explicitly install the pinned version from the official uv instructions." >&2
  exit 1
fi
[[ "$("$uv_bin" --version)" == "uv $uv_version "* ]] || { echo "Expected uv $uv_version" >&2; exit 1; }
[[ "$(node --version)" == v24.19.0 ]] || { echo 'Expected Node 24.19.0' >&2; exit 1; }
[[ "$(pnpm --version)" == 11.19.0 ]] || { echo 'Expected pnpm 11.19.0' >&2; exit 1; }
"$uv_bin" python install "$python_version" --no-bin
"$uv_bin" sync --project backend --locked --extra entities --extra publication
"$uv_bin" run --project backend --locked --no-sync python scripts/export-contracts.py
"$uv_bin" run --project backend --locked --no-sync python scripts/generate-fixtures.py
"$uv_bin" run --project backend --locked --no-sync python scripts/export-fixture-cases.py
pnpm --dir frontend install --frozen-lockfile --store-dir "$repo_root/.cache/pnpm-store"
node "$repo_root/frontend/node_modules/@playwright/test/cli.js" install chromium
echo 'Foundation dependencies installed. Run scripts/run-checks.sh separately.'
echo 'On Linux, Playwright OS libraries must already be installed; an explicit playwright install --with-deps chromium requires system package-installation authorization.'
