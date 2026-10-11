# RegIntel Finance — Astra/Codex Final Execution Runbook

## 1. Operating model

Use this ChatGPT account as the **project brain**:

- research interpretation;
- architecture decisions;
- scope control;
- experiment design;
- review of Astra output;
- targeted debugging decisions;
- short execution prompts.

Use Astra/Codex as the **execution engine**:

- repository inspection;
- code;
- tests;
- dependency installation;
- migrations;
- Docker;
- terminal work;
- debugging;
- refactoring within approved scope.

The goal is to avoid paying Astra context to rediscover the project.

## 2. Progressive disclosure

Do NOT make Astra read every document on every task.

Stable context:

```text
AGENTS.md
CURRENT_STATE.md
```

Use additional documents only when relevant:

- architecture task → `SYSTEM_ARCHITECTURE_FINAL.md`
- M1 task → `M1_RESEARCH_METHOD_FINAL.md`
- stack/dependency task → `TECH_STACK_AND_DATA_FINAL.md`
- evaluation task → `EVALUATION_PLAN_FINAL.md`
- runtime LLM task → `RUNTIME_MODEL_CONTRACT_FINAL.md`
- phase implementation → the specific phase in `BUILD_PHASES_FINAL.md`

## 3. First Astra run — read only

Prompt:

```text
You are working on RegIntel Finance.

Do not modify files yet.

Read:
- AGENTS.md, if present
- CURRENT_STATE.md, if present
- PROJECT_CHARTER_FINAL.md
- SYSTEM_ARCHITECTURE_FINAL.md
- TECH_STACK_AND_DATA_FINAL.md
- BUILD_PHASES_FINAL.md

Inspect the repository and local environment.

Report:
1. current repository structure;
2. current implementation status;
3. runtime/tool versions;
4. missing prerequisites;
5. contradictions between repository and specification;
6. likely technical blockers;
7. a concrete Phase 0 implementation plan.

Do not install packages.
Do not modify files.
Do not create code.
Wait for approval.
```

## 4. Execution model: milestones, not micro-phases

Do not force one model call per tiny phase when a coherent implementation block can be safely completed in one run.

Recommended milestones:

### M0 — Foundation

0.1–0.6:

- repository;
- agent rules;
- toolchain;
- database;
- authentication;
- shared contracts;
- fixture/test infrastructure.

### M1A — Ingestion/evidence

1.1–1.4:

- filing data model;
- upload/job;
- parser;
- source geometry/evidence.

### M1B — Extraction/validation/versioning

1.5–1.9:

- entity resolution;
- candidate extraction;
- validation;
- review/quarantine;
- ingestion recovery;
- amendment lineage/effects;
- publication/projection.

### M1C — APIs/retrieval/admin

1.10–1.12:

- company/fact/graph APIs;
- B0–B3 retrieval;
- bounded Q&A;
- review/admin UI.

### M2 — Comparison

Company profile → evidence viewer → normalization → formulas → comparison → evaluation.

### M3 — Learning

Glossary → source-linked explanations → optional constrained paraphrase → evaluation.

### M4 — Portfolio

Ledger → quote snapshots → orders → invariants → analytics → evaluation.

### INTEGRATION

I.1 vertical slice → I.2 freeze → I.3 held-out evaluation → I.4 reproduction/handoff.

## 5. What Astra can normally do without asking

- edit project files;
- create tests;
- install project-local dependencies;
- create virtual environments;
- run uv/pnpm;
- run Docker Compose;
- run migrations in the development database;
- run tests;
- inspect logs;
- update `CURRENT_STATE.md`;
- create a local commit when the milestone is explicitly approved.

## 6. Explicit approval required

Ask before:

- deleting large unrelated file groups;
- destructive Git resets/clean operations;
- system-wide configuration changes;
- unexpected system-level software installation;
- paid API usage beyond the agreed budget;
- public port exposure;
- accessing credentials;
- pushing to a remote repository;
- changing architecture outside the current milestone;
- introducing major infrastructure not specified.

Never put API keys, passwords or private tokens in prompts.

## 7. Milestone prompt pattern

```text
Context:
<why this milestone exists>

Read:
<only relevant documents>

Implement:
<exact milestone scope>

Do not:
<boundaries / out-of-scope items>

Acceptance:
<observable completion criteria>

Verify:
<commands/tests>

At the end:
- files changed
- tests/checks run
- results
- dependencies added
- migrations added
- environment variables added
- limitations
- current_state update
```

## 8. Completion standard

“Implemented” is not enough.

A milestone is complete only when:

- code exists;
- relevant tests/checks pass;
- actual commands are reported;
- no unresolved critical failure is hidden;
- `CURRENT_STATE.md` is updated.

## 9. When Astra gets stuck

Do not repeatedly ask it to “try harder.”

Bring the exact blocker back here and classify it:

- architecture;
- algorithm;
- package/version;
- parser limitation;
- data issue;
- test failure;
- machine resource;
- ambiguous requirement.

Then issue one targeted execution instruction.

## 10. Context-saving rule

Never ask Astra:

> Explain the entire project again.

Ask:

> Implement/fix X under the current architecture, using Y contract, and verify Z.

## 11. Git

Protect the working tree.

Never ask Astra to use blanket destructive commands such as:

```text
git reset --hard
git clean -fd
git checkout -- .
```

A milestone may be committed after review. The working branch should remain recoverable at every milestone.
