# MEDHA Frontend

Bright Mode deployment console.

## Run (with backend)

```bash
# terminal 1
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# terminal 2
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

Same-origin by default: the browser calls relative `/api/*` URLs, which the
production service proxies to FastAPI via Next.js rewrites (see root
`render.yaml` / `DECISIONS.md` ADR-026). `NEXT_PUBLIC_API_BASE_URL` only
overrides this for split local development (default `http://127.0.0.1:8000`).

## Tests

```bash
cd frontend
npm test        # vitest unit/component tests
npm run lint    # eslint (next lint)
npm run build   # typecheck + production build
```

Tests cover event mapping (demo/live state transitions, terminal statuses, SSE
reconcile fallback) and UI status helpers.

## Change Intelligence panel (Phase 12/2)

`src/components/changeintel/ChangeImpactPanel.tsx` renders the **Change Impact
Graph (CIG)** — visually distinct from the CEG — with evidence-labelled
dependency edges, risk factor list, changed files, direct/transitive impact,
unresolved dependencies, and verification requirements (executable vs
source-level, never faked). It consumes `snapshot.changeIntel` from the live
SSE pipeline or a labelled `DEMO/MOCK` fixture; in the idle state a
"Load demo fixture" button fetches `GET /api/change-impact/demo/fixture`.

Live payloads arrive on the ANALYZE stage via `data.change_intel` (mapped in
`src/lib/api/eventMapper.ts`).

## Phase notes

- Phase 1: UI + local mock frames (demo fixtures kept separate from live events)
- Phase 2–12: UI posts to FastAPI and consumes SSE for demo and real pipeline
  events; demo/live labels are derived from application state, never hardcoded.
