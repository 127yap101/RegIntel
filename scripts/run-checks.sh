#!/usr/bin/env bash
# Run setup/locked dependency installs before this script. No installs or
# infrastructure startup occur here. Playwright uses localhost web servers.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"

skip_browser=false
if [[ ${1:-} == "--skip-browser" ]]; then
  skip_browser=true
  shift
fi
if [[ $# -ne 0 ]]; then
  printf 'Usage: bash scripts/run-checks.sh [--skip-browser]\n' >&2
  exit 2
fi

if [[ -x "$project_root/.tools/uv/uv" ]]; then
  uv_executable="$project_root/.tools/uv/uv"
elif [[ -x "$project_root/.tools/uv/uv.exe" ]]; then
  uv_executable="$project_root/.tools/uv/uv.exe"
elif command -v uv >/dev/null 2>&1; then
  uv_executable="$(command -v uv)"
else
  printf 'uv is missing. Complete the documented project toolchain setup first.\n' >&2
  exit 1
fi
for command_name in node pnpm; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf '%s is missing. Complete toolchain setup before running checks.\n' "$command_name" >&2
    exit 1
  fi
done
if [[ "$(pnpm --version)" != "11.19.0" ]]; then
  printf 'Expected documented pnpm11.19.0; restore the project toolchain before checks.\n' >&2
  exit 1
fi
for required_path in backend/uv.lock backend/.venv frontend/package.json frontend/node_modules; do
  if [[ ! -e "$required_path" ]]; then
    printf 'Missing %s. Complete the documented locked dependency installs first.\n' "$required_path" >&2
    exit 1
  fi
done

export UV_CACHE_DIR="$project_root/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$project_root/.tools/python"
export UV_PYTHON_DOWNLOADS=never
export PLAYWRIGHT_BROWSERS_PATH="$project_root/.cache/ms-playwright"
export COREPACK_ENABLE_NETWORK=0

run_check() {
  printf 'Running:'
  printf ' %q' "$@"
  printf '\n'
  "$@"
}

run_check "$uv_executable" --version
run_check node --version
run_check pnpm --version
run_check "$uv_executable" lock --project backend --check --offline
uv_run=("$uv_executable" run --project backend --locked --no-sync --offline --no-python-downloads)
run_check "${uv_run[@]}" python scripts/export-contracts.py --check
run_check "${uv_run[@]}" python scripts/export-published-reads.py --check
run_check "${uv_run[@]}" python scripts/export-retrieval.py --check
run_check "${uv_run[@]}" python scripts/export-admin.py --check
run_check "${uv_run[@]}" python scripts/export-analysis.py --check
run_check "${uv_run[@]}" python scripts/generate-analysis-fixtures.py --check
run_check "${uv_run[@]}" python scripts/generate-read-fixtures.py --check
run_check "${uv_run[@]}" python scripts/generate-fixtures.py --check
run_check "${uv_run[@]}" python scripts/export-fixture-cases.py --check
python_check_paths=(backend scripts/init-local-env.py scripts/init-auth-env.py scripts/check-infra.py scripts/check-migrations.py scripts/check-ingestion-runtime.py scripts/check-evidence-runtime.py scripts/check-entity-runtime.py scripts/check-candidate-runtime.py scripts/check-validation-runtime.py scripts/check-processing-runtime.py scripts/check-publication-runtime.py scripts/check-published-reads-runtime.py scripts/check-retrieval-runtime.py scripts/acquire-embedding-model.py scripts/export-contracts.py scripts/export-published-reads.py scripts/export-retrieval.py scripts/export-admin.py scripts/export-analysis.py scripts/generate-analysis-fixtures.py scripts/check-analysis-runtime.py scripts/evaluate-analysis.py scripts/probe-numerical-page.py scripts/generate-read-fixtures.py scripts/generate-fixtures.py scripts/export-fixture-cases.py scripts/acquire-worker-libs.py scripts/inspect-docling-source.py scripts/render-parse-qa.py)
run_check "${uv_run[@]}" ruff check --config backend/pyproject.toml "${python_check_paths[@]}"
run_check "${uv_run[@]}" ruff format --check --config backend/pyproject.toml "${python_check_paths[@]}"
run_check "${uv_run[@]}" mypy --config-file backend/pyproject.toml backend/src scripts/init-local-env.py scripts/init-auth-env.py scripts/check-infra.py scripts/check-migrations.py scripts/check-ingestion-runtime.py scripts/check-evidence-runtime.py scripts/check-entity-runtime.py scripts/check-candidate-runtime.py scripts/check-validation-runtime.py scripts/check-processing-runtime.py scripts/check-publication-runtime.py scripts/check-published-reads-runtime.py scripts/check-retrieval-runtime.py scripts/acquire-embedding-model.py scripts/export-contracts.py scripts/export-published-reads.py scripts/export-retrieval.py scripts/export-admin.py scripts/export-analysis.py scripts/generate-analysis-fixtures.py scripts/check-analysis-runtime.py scripts/evaluate-analysis.py scripts/probe-numerical-page.py scripts/generate-read-fixtures.py scripts/generate-fixtures.py scripts/export-fixture-cases.py scripts/acquire-worker-libs.py scripts/inspect-docling-source.py scripts/render-parse-qa.py
mkdir -p "$project_root/.cache"
pytest_run_directory="$(mktemp -d "$project_root/.cache/pytest-checks.XXXXXXXX")"
case "$pytest_run_directory" in
  "$project_root/.cache/pytest-checks."*) ;;
  *) printf 'Pytest temporary target escaped the project cache.\n' >&2; exit 1 ;;
esac
run_check "${uv_run[@]}" pytest backend/tests --basetemp "$pytest_run_directory/tmp" -o "cache_dir=$pytest_run_directory/cache"
pnpm_frontend=(pnpm --dir frontend --config.verify-deps-before-run=error)
for check_name in lint typecheck test build; do
  run_check "${pnpm_frontend[@]}" run "$check_name"
done
if [[ "$skip_browser" == true ]]; then
  printf 'Browser smoke test explicitly skipped (--skip-browser).\n'
else
  run_check "${pnpm_frontend[@]}" run test:e2e
fi
printf 'Foundation checks passed.\n'
