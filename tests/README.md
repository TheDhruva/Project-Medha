# tests/

Automated tests for MEDHA.

## Backend (`backend/tests/`)

Run: `cd backend && pytest -q`

- Demo-mode API, SSE replay/terminal, and REST endpoints
- Real-mode planning pipeline (success, partial failure + scoped rollback, replan)
- CNP/CEG evaluation runners + baseline comparison
- Deploy lock (single-flight, `409 DEPLOYMENT_BUSY`)
- Database init + versioned schema migrations (incl. legacy-schema upgrades)
- **Change Intelligence (Phase 12/2):** fixture-based unit tests (11 local git
  repos: risk expectations, edge evidence, error codes), a full-chain
  integration test (git → diff → symbols → CIG → risk → requirements → stored →
  API), and end-to-end API tests (analyze / persisted / demo fixture).
- Docker-mutating tests are marked `docker` and skipped when no daemon is available

To (re)build the git fixtures:

```bash
cd backend
.venv\Scripts\python.exe tests\fixtures\change_intel\_build.py
```

## Frontend (`frontend/src/**/*.test.ts(x)`)

Run: `cd frontend && npm test`

- Event mapping: demo/live state transitions, terminal statuses, SSE reconcile fallback
- UI status helpers (mode label derivation, stage tones)
- Change-intel client (POST/GET/demo-fixture URLs + error-code surfacing) and
  ChangeImpactPanel rendering (risk, DEMO/MOCK label, changed files, unresolved
  deps, requirements, edge evidence)
- Phase 2 layout util is covered via the panel; typecheck via `npx tsc --noEmit`

All current runs are verified green (see phase reports).