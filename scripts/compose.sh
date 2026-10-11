#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$repo_root/.env" ]] || { echo 'Generate .env with scripts/init-local-env.py first.' >&2; exit 1; }
mkdir -p "$repo_root/.cache/docker"
[[ -f "$repo_root/.cache/docker/config.json" ]] || printf '{}\n' > "$repo_root/.cache/docker/config.json"
# Explicit local socket; never reuse registry credentials from the user's Docker config.
docker_socket="${REGINTEL_DOCKER_SOCKET:-/var/run/docker.sock}"
if [[ -z "${REGINTEL_DOCKER_SOCKET:-}" && ! -S "$docker_socket" && -S "$HOME/.docker/run/docker.sock" ]]; then
  docker_socket="$HOME/.docker/run/docker.sock"
fi
[[ "$docker_socket" == /* && -S "$docker_socket" ]] || { echo 'Set REGINTEL_DOCKER_SOCKET to an existing absolute local Unix socket path.' >&2; exit 1; }
docker_args=(docker --config "$repo_root/.cache/docker" --host "unix://$docker_socket" compose --env-file "$repo_root/.env" -f "$repo_root/infra/compose.yaml")
case "${1:-}" in
  worker-build) "${docker_args[@]}" --profile ingestion build worker ;;
  worker-up) "${docker_args[@]}" --profile ingestion up -d --wait --wait-timeout 180 worker ;;
  worker-status) "${docker_args[@]}" --profile ingestion ps worker ;;
  worker-restart) "${docker_args[@]}" --profile ingestion restart --timeout 30 worker ;;
  worker-stop) "${docker_args[@]}" --profile ingestion stop --timeout 30 worker ;;
  validate) "${docker_args[@]}" config --quiet ;;
  pull) "${docker_args[@]}" pull ;;
  up) "${docker_args[@]}" up -d --wait --wait-timeout 180 ;;
  status) "${docker_args[@]}" ps ;;
  restart) "${docker_args[@]}" restart --timeout 30 ;;
  stop) "${docker_args[@]}" stop --timeout 30 ;;
  images) "${docker_args[@]}" images ;;
  *) echo 'Usage: bash scripts/compose.sh validate|pull|up|status|restart|stop|images|worker-build|worker-up|worker-status|worker-restart|worker-stop' >&2; exit 2 ;;
esac
