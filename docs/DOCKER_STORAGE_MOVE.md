# Docker storage relocation checkpoint

User authorized moving existing Docker Desktop storage from C: to `D:\DockerData` on 11 October 2026. This is environment maintenance; M1A remains complete and M1B is not started by this action.

## Completed and verified, 11 October

The user applied Docker Desktop's supported location setting. Both live WSL disks now exist under **`D:\DockerData\DockerDesktopWSL`**; the original C: disk paths are absent. Engine29.7.2 is responding; the original PostgreSQL, Neo4j, Redis and worker services were restarted without rebuilding and are healthy. All three named volumes retain their5October creation timestamps; worker image/security/bind mounts and loopback-only ports are preserved.

The read-only preservation check passed: migrations1-5 and all checksums; generated admin/learner authentication; existing PARSED job/attempt1; artifact/configuration/exact evidence fingerprints; 878 records; eight original-PDF full/range/HEAD/conditional/auth checks; unchanged authoritative/legacy snapshots and zero future-authority counts. No new ingestion, duplicate dispatch, publication or DB migration was performed. The temporary API was stopped.

Measured at09:09UTC: C: **36,165,128,192 bytes free (~36.2GB)**; D: **43,109,076,992 bytes free (~43.1GB)**. D: includes both the live Docker disks and the retained verified29.4GB cold backup. The external X: drive was not modified.

Proofs: `.cache/docker-storage-verification-bba8913f8fcc45d1a7bc2abb63442b07/verification-report.json` and `storage-verification.json`. The image/volume/container metadata was independently checked. Full application tests were not repeated because product code, dependencies and migrations did not change; the existing-state preservation checks address this operation.

## Preparation history

- Docker Desktop and its VM were stopped before copying. Exclusive file access protects against backing up a mounted disk.
- A cold backup is complete in the ignored project cache under `D:\RegIntel\.cache\docker-storage-backups\20261011-142236-ae158942fb9e4b7680a1bb17ec0d03d9`.
- Both disk copies passed byte-length and SHA-256 verification; the settings-store copy passed hash verification. The verified report is `backup-report.json` in that directory. Data VHDX: 29,329,719,296 bytes, SHA-256 `8b42d62803798769dbbb109cc72503a0578ad830d0321e3a4204e75dd23f6535`. Main VHDX: 100,663,296 bytes, SHA-256 `bcb08e6a2d5d3c15c8b4bd91ca3d2acc872c94b93ac7793f0057e8111012f3dd`.
- After backup, D: has 72,557,363,200 bytes free and C: has 7,501,967,360 bytes free. Backup storage consumes about 29.4 GB on D:; moving the live data there will consume additional space. Keep the backup until the post-move checks pass.
- Before the user applied the move, `D:\DockerData` was created empty and the original Docker disks remained in place.
- Desktop-control initialization failed twice with `failed to write kernel assets: The system cannot find the path specified. (os error 3)`. The supported GUI step currently needs the user. No manual disk move, settings edit, reset or pruning is used as a substitute.
- The documented CLI accepted `docker desktop start --detach`, but a subsequent status check could not retrieve Desktop status and the Linux engine pipe was absent. Startup/engine readiness is not verified; open Desktop manually before changing its storage setting.

## Supported procedure used

1. Open Docker Desktop manually and wait for **Engine running**. If it reports an error, report that message before proceeding.
2. Open **Settings → Resources → Advanced**.
3. Change **Disk image location** to `D:\DockerData` using **Browse**.
4. Apply the change and restart when Docker requests it. Keep the laptop awake and plugged in until the move finishes.
5. If the location control is missing or Docker reports an error, retain the backup and original disks and report the exact message. Do not use reset, uninstall, prune or WSL unregister to resolve it.

The source project, filings and model bind mounts already use `D:\RegIntel`; this operation needs no Compose path changes. The backup remains separate from the destination.

## Verification checklist completed

The actual VHDX location on D:, C: free-space recovery, engine health, original volumes/image identities and the existing M1A state are verified. Only the existing Compose services and worker were restarted; no rebuild was performed.

- Migration status must remain applied `[1,2,3,4,5]`, pending `[]`, with the existing migration checksums.
- Existing job `c81a8c48-2895-4c00-8d88-e45a99bd114e` must remain `PARSED`, attempt 1, parse `38819124-f764-4f41-acef-44ac000dbc45`, artifact SHA-256 `f430e07dca943d6b0bf2266fc839475bfe19bf1bfe78a0c225620195c6a5880f` and 878 exact evidence records.
- Verify existing generated account authentication and evidence `a2491199-24e3-439f-bba6-3e380db8a28d`, and original source hash `a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347`.
- Do not submit a new ingestion job as a storage verification probe. Keep the verified backup until these checks pass.

Official references: [Docker WSL storage location](https://docs.docker.com/desktop/features/wsl/), [cold VM backup and restore](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/), [Desktop CLI commands](https://docs.docker.com/reference/cli/docker/desktop/).
