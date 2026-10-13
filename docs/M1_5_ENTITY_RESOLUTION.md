# M1.5 — Evidence-backed entity resolution

Status: verified and complete on 13 October 2026. This document is an execution record, not a change to the finalized design. M1.6–M1.9 remain later work.

## Scope and authority

The native administrator API operates on exact text evidence from an already sealed PARSED filing. It does not reparse PDFs, mutate terminal ingestion jobs, accept financial facts/relations, resolve amendment effects, publish a corpus or change Neo4j. PostgreSQL stores immutable identity approvals, resolver snapshots, mentions and review decisions. Migrations0001–0005 remain unchanged;0006 adds the entity subsystem and retains all existing financial authority gates.

The existing Windows/native API plus non-root Linux parser worker exception remains approved. The M1.5 runtime is native; the retained M1A worker image is a historical parser runtime and has not been rebuilt with the new source/lock. Checkpointed Celery integration is M1.8 work. No provider call is required here.

## Resolution contract

An administrator registers a canonical UUIDv4 entity, its exact source-backed legal name, any explicitly reviewed aliases and structurally valid CIN/ISIN identifiers. Each term references a persisted evidence ID and half-open absolute Unicode code-point offsets into its original block. CIN shape and ISIN check digits are validated. Identifier uniqueness is global by type/value; approved alias collisions remain possible and require review. Registrations retain reviewer identity/version and an explanation; identical replay is a no-op. No filing metadata is overwritten to assign an entity.

Detection uses a blank English spaCy pipeline with EntityRuler, bounded CIN/ISIN patterns and a bounded legal-company-name proposal pattern. No pretrained NER model, transformer, GPU or model download is introduced. EntityRuler patterns identify source spans; canonical identity is resolved through a separate registry index so colliding aliases cannot silently select an entity.

Mention subspans retain their parent evidence ID and its measured source-page geometry. No word-level rectangles are fitted or invented from character offsets; the existing evidence viewer can display the parent source region.

Resolution follows exact CIN/ISIN, exact approved name/alias, normalized approved name, then RapidFuzz proposals. Normalization is Unicode NFKC, casefold and punctuation/whitespace separation; it does not delete legal suffixes, translate names or invent aliases. Conflicting known identifier context and ambiguous names require review. Unknown identifiers stay unresolved. Fuzzy proposals always have REVIEW state, even at a score of100; their score is similarity, not financial confidence or acceptance.

The default fuzzy threshold85 and at most five proposals are explicitly configured engineering choices, not tuned research outcomes. A run refuses more than10000 exact evidence records or25000 mentions without persisting a partial result. Detection covers local exact text, not unavailable table-cell originals; bounded proposal regexes can miss unfamiliar person/organization names and noisy OCR. No entity/relation recall result is claimed.

ISIN identifies a security/instrument; its reviewed association with an entity does not establish ownership or a corporate relationship. Syntax/check-digit validation is not proof that an identifier was allocated or that an issuer mapping is correct. The implementation follows the published12-character and modulus10 structure described by [ANNA, the ISO6166 registration authority](https://anna-web.org/identifiers/); source evidence and administrator review establish the stored association.

## Immutable storage and review

Each run binds the parse/artifact identity, complete exact evidence collection, registry revision/hash, actual spaCy/RapidFuzz versions and resolver-code/configuration hash. Submission is rederived from authoritative source and registry before persistence. It is atomically sealed with its mentions; identical replay preserves its identity. A changed registry requires a new run, while old runs remain readable.

An administrator may RESOLVE a mention to one of its existing frozen proposals or REJECT it, with exact evidence from the same parse and an explanation. This stores a separate final audit. It does not overwrite the original automatic outcome, approve a new alias or accept a financial observation. Consumers must read both the immutable run and its review decisions; REJECT removes that mention from usable resolved identities, and RESOLVE selects the reviewed proposal. Unreviewed fuzzy/ambiguous mentions supply no authoritative canonical ID.

Registry registrations are one immutable legal-name/alias/identifier batch per entity. Additional alias approval/editing and review corrections are not implemented by these endpoints; there is no silent overwrite. Review replay requires the same audit ID and payload; different IDs or decisions conflict. A registration discovered after a run requires rerunning against the updated registry before selecting its entity.

## API and local reproduction

All endpoints use existing database-authoritative administrator authentication, no-store responses and typed envelopes. Learners and anonymous callers cannot access them. Account activity/role/authentication version is checked again inside write transactions.

| Endpoint | Behavior |
|---|---|
| POST /v1/admin/entities | Register one reviewed source-backed identity; receipt identifies whether it already existed |
| POST /v1/admin/entities/runs | Supply parse_version_id; derive and persist the complete bounded resolver run |
| GET /v1/admin/entities/runs/{run_id} | Read immutable run plus separately recorded reviews |
| POST /v1/admin/entities/reviews | Record a source-backed final entity mapping/rejection |

The native production `entities` extra supplies spaCy3.8.16 and RapidFuzz3.14.6 with locked transitive dependencies; both bootstrap scripts and CI select it, while the parser worker continues selecting only `parsing`; no environment variables are added. After documented locked setup and migration verification, use the configured native API:

```powershell
.\backend\.venv\Scripts\regintel-api.exe --env-file .env --auth-env-file .env.auth
```

For the existing controlled Premier parse, the real proof helper is:

```powershell
.\backend\.venv\Scripts\python.exe scripts/check-entity-runtime.py --parse-version-id 38819124-f764-4f41-acef-44ac000dbc45
```

That parse UUID exists only on the original verified machine. A teammate must first reproduce ingestion/evidence on their own machine and use its actual parse UUID. The helper requires the original controlled source hash, generated local accounts and a configured loopback API. It registers only the verified issuer name/CIN, derives/replays the run, checks anonymous/learner denial and original evidence reads, and compares source/jobs/financial state before and after. It saves a new ignored proof directory. Original PDFs, model/runtime assets, credentials, database state and generated proofs remain out of Git.

## Verification record

Primary0006 is applied and frozen at8c9fefdf88fc7cf7f762e8d90375b645cd7bc30f91b89c2022a6d04de34f8249; migrations1–6 applied, none pending. Real Premier run407bc0fa-e97a-4d81-8c9f-126b682e83a7 scans878exact records and persists40mentions:6RESOLVED/1REVIEW/33UNRESOLVED. Source-backed issuer/CIN, replay, original evidence, authentication denials and unchanged source/job/financial snapshots pass. Temporary proofAPI was stopped. See data/entity-validation-report.json for actual identities/configuration/limitations.

Full checks pass1116backend/6Windows skips,208live DB,212frontend/3Chromium, lint/types/build, Ruff111 and strict mypy72; final scoped helper checks and Linux-platform mypy62 pass. Independent review findings were repaired and exercised by tests. CI portability checkpointcb772a8 is hosted-green; this entity source requires its own hosted result. Unit/model fixture scores are engineering tests only. Real gold annotation and held-out evaluation remain unperformed.
