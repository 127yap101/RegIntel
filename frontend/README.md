# RegIntel frontend foundation

M0.2 provides the React, strict TypeScript, Vite and Tailwind foundation. The welcome page checks backend liveness; M1–M4 business modules and company data are absent.

Use Node 24.19 and pnpm 11.19. First run the repository-root bootstrap, which installs
locked dependencies and generates the ignored contract schema/types and synthetic
fixture case data required by frontend checks. If dependencies are already installed,
regenerate after changing Python contracts or fixture builders from the root:

```powershell
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/export-contracts.py
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/export-fixture-cases.py
```

Then run these commands from `frontend/`:

```powershell
pnpm dev
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm test:e2e
```

Development and preview bind to `127.0.0.1:5173` with a strict port. `VITE_API_BASE_URL` defaults to `http://127.0.0.1:8000`; `.env.example` contains the non-secret example. This value is public browser configuration and must never contain credentials.

The health client validates `GET /health/live`, applies a five-second timeout, and distinguishes unavailable/invalid responses from a healthy backend. A healthy result proves liveness only, not implementation of business modules.

Vitest/Testing Library tests cover accessible controls, health contract failures and retry behavior. Playwright starts the locked backend offline through the root-local uv tool (or uv on PATH), plus a dedicated localhost Vite server. One browser smoke case connects to the actual FastAPI health endpoint; two explicitly network-controlled cases cover narrow-screen accessibility and unavailable-to-available recovery. No business-module functionality is implied.

M0.5 adds Ajv8.20.0 and ajv-formats3.0.1 for draft2020-12 runtime contract
validation. `src/contracts/runtime.ts` validates unknown wire data without
coercion, defaults or property removal and checks cross-field invariants. Financial
values remain branded decimal strings; this frontend performs no authoritative
arithmetic. The root check runner verifies generated-artifact drift before frontend
checks. The shared parity vectors and runtime boundary cases are synthetic fixtures.

M0.6 exports authored synthetic scenarios to the ignored
`src/contracts/fixtures.generated.json`. `src/contracts/fixtures.test.ts` runs
40 tests against current wire structure, retaining exact decimal/raw strings and
checking input immutability. Timeout/refusal scenarios have no wire payload and do
not call the validator. The complete frontend suite currently passes 212 tests.
Scenario `future_expectation` values describe intended later M1 gates and runtime
behavior; those gates are not implemented or verified by these fixture tests.

Playwright browsers are installed by the root verification workflow, which sets `PLAYWRIGHT_BROWSERS_PATH` to the repository cache. Never count unrun browser tests as passing.
