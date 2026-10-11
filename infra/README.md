# Local infrastructure (M0.3)

PostgreSQL16+pgvector is authoritative; Neo4j is a future rebuildable published graph; Redis supports later Celery jobs. M0.3 establishes connectivity/persistence and migration infrastructure only. Services bind to127.0.0.1, use separate named volumes and do not restart automatically. No business data is supplied.

Start the existing Docker Desktop Linux engine first. From the root, with bootstrapped Python:

```powershell
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/init-local-env.py
.\scripts\compose.ps1 validate
.\scripts\compose.ps1 pull
.\scripts\compose.ps1 up
.\scripts\compose.ps1 status
```

The generator creates new ignored `.env` secrets and refuses an existing file. No original credentials are read. Compose wrappers use a project-local Docker configuration without registry credentials and the explicit local engine. Windows records only the installed plugin directory in that local configuration. `stop` retains all named volumes; no deletion action is provided. PostgreSQL readiness is supplemented by authenticated migration/SQL checks. Redis AOF/everysec must be verified with an orderly restart, without a zero-loss/crash durability claim. Neo4j Browser7474 is not exposed.

Linux/macOS use `bash scripts/compose.sh <action>` with their local Docker socket. The wrapper checks `/var/run/docker.sock`, then Docker Desktop's `~/.docker/run/docker.sock`, or the explicitly configured absolute `REGINTEL_DOCKER_SOCKET`. No socket/system setting is changed. Generated secret-file protection on Windows follows the workspace's inherited NTFS ACLs; Unix creation requests mode0600. Actual image digests/server versions and complete acceptance results are recorded after measurement in `docs/dependency_versions.md` and `docs/PHASE_LOG.md`.

Verified database and infrastructure acceptance commands (from the root):

```powershell
.\.tools\uv\uv.exe run --project backend --locked --no-sync regintel-db migrate --env-file .env
.\.tools\uv\uv.exe run --project backend --locked --no-sync regintel-db migrate --env-file .env
.\.tools\uv\uv.exe run --project backend --locked --no-sync regintel-db check --env-file .env
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/check-migrations.py
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/check-infra.py --restart
```

The repeat migration must be a no-op. The live test helper creates a fresh `regintel_test_...` database, runs all live backend integration tests (54 at M0.4), and removes only that test database. It refuses query overrides in generated configuration and never force-disconnects other sessions. Check runners use fresh ignored project-cache pytest directories to avoid Windows sandbox/user temp ACL conflicts. The infrastructure checker verifies exact loopback bindings, named volumes, service/extension versions, Redis authentication/non-root/AOF policy, and temporary synthetic probes including an exact NUMERIC/Decimal round-trip. `--restart` restarts only RegIntel containers and cleans each identified probe independently; any retained probe is reported by its UUID and acceptance fails. Without that flag persistence is explicitly reported unrun.

Desktop initially failed on stale host AF_UNIX sockets. Approved socket-only runtime directory isolation allowed engine startup and preserved backups; see the phase log. A future full Desktop restart may need troubleshooting; no factory reset, data-disk or WSL-registration change was performed. Never run expanded `compose config` or dump container environment into a shared transcript because credentials would appear.
