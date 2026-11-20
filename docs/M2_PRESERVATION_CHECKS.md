# M2 acceptance: preservation scope

Updated 20 November 2026. The acceptance evaluator now uses the installed
`regintel.db.snapshot` helper and its explicitly selected database settings.
`--source-project` selects the existing configuration and source assets; it does
not supply Python code to execute. An older assets checkout cannot select an
older preservation implementation.

## What the check covers

Each before/after snapshot opens one PostgreSQL transaction with repeatable-read
isolation and read-only enforcement. It validates the installed migration names
and checksums and requires complete migration history. It then discovers current
`regintel` base tables and the `regintel_meta.schema_migrations` ledger through
the database catalog. It does not maintain the former fixed list of37 tables.

Rows are ordered deterministically, encoded with UTC dates and UTF-8, and hashed
with byte-length framing. A server cursor fetches bounded batches. Reports retain
qualified table names and SHA-256 digests; they do not export raw database rows.
Row changes and table additions/removals make the before/after maps differ and
fail the preservation check. Incomplete/changed migration history, a missing
application schema, unreadable tables or unsupported foreign tables cannot
produce a successful preservation result. Row-security filtering is disabled
for the read so a restricted role fails rather than silently hashing a subset.

The report declares `state_snapshot_version=current-database-rows-1`. Its digest
format and schema-qualified keys differ from older reports; do not compare them
as if they were the same snapshot format.

This is a row and table-inventory preservation check, not a complete database
schema audit. It does not hash sequence counters, every schema object or external
Neo4j state. Run it during a quiet period: a legitimate concurrent write can
fail the comparison, and equal endpoints do not prove no transient change ever
occurred between them. The helper itself uses PostgreSQL read-only enforcement.

## Actual controlled-corpus result

The20November run recorded at12:00:25UTC produced **BLOCKED**, as expected for
the current unreviewed numerical acceptance plan:

| Report field | Measured result |
|---|---:|
| Published companies | 1 |
| Active published observations | 1 |
| Active numerical facts | 0 |
| Numerical metric definitions in the published catalog | 0 |
| Acceptance cases executed / passed / failed | 0 / 0 / 0 |
| Required categories still missing | 6 |
| Preserved tables and migration ledger | 70 |
| Model/provider calls | 0 |

The70 digests comprise69 application tables and the migration ledger. Reviewer
metadata remains absent. The original conditional narrative remains published;
these measurements do not approve or publish any numerical input, definition,
price or comparison case. Zero failed cases with zero executed cases is not an
acceptance pass or a research result.

The private receipt is
`.cache/analysis-acceptance-45367c17bdcd4df286f646eec990ac56/report.json` in the
integration checkout. A teammate's clone does not include that private receipt,
database or original sources. Use [the acceptance guide](M2_ACCEPTANCE.md) to
prepare an independently reviewed plan against that installation's published
corpus; the existing approval and publication prerequisites still apply.
