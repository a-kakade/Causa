# API Integration Plan

Status: implemented. This document records the audit and the plan that was executed to connect the React/Vite frontend to the existing Steps 1-9 Python engines via a new FastAPI layer (`causa/api/`).

## Existing service boundaries (before this work)

- **Engines** (`causa/src/`): `kpi/`, `anomaly/`, `drivers/`, `evidence/`, `agents/` (+ `tools/`), `causal/`, `decision/`, `story/`, `feedback/` — each a pure-Python package with one or a few public entry points (`KPIEngine.compute`, `anomaly.engine.detect`, `drivers.engine.decompose`, `agents.orchestrator.run_investigation`, `causal.engine.run_causal_analysis`, `decision.ranking.run_decision_pipeline`, `story.engine.generate_kpi_story`, `feedback/*`). No engine file was modified to build the API.
- **Demo/CLI scripts** (`causa/scripts/stepN_*.py`): the only existing "callers" of the engines before this work — each builds real objects, runs them, and writes `causa/reports/stepN_validation.json`. `scripts/step5_investigate_november_2017.py` in particular is the pattern the API's `bootstrap.py` and the investigation replay path reuse directly.
- **Persistence**: Parquet (`data/processed/`), one-shot JSON reports (`reports/`), append-only JSONL (`data/feedback/`, Step 9 only). No database anywhere.
- **Frontend** (`frontend/`): React/Vite app with 9 pages already built against `demoAdapter` (static JSON fixtures) behind a one-line-swap seam (`frontend/src/api/index.ts`), with TypeScript types in `frontend/src/types/*.ts` that already mirror the backend dataclasses field-for-field.
- **No HTTP surface existed anywhere in the repo** prior to this work (confirmed: no fastapi/flask/uvicorn in `causa/requirements.txt` or anywhere in the codebase).

## What was built

A new `causa/api/` package (FastAPI + Pydantic-request-models, plain-dict responses) sitting between the frontend and `causa/src/`:

```
Frontend (productionApi/*.ts)
    -> HTTP (fetch, ?requester_role=)
    -> causa/api/routes/*.py  (thin controllers)
    -> causa/api/*.py services (bootstrap, store) + direct calls into causa/src/
    -> causa/src/{kpi,anomaly,drivers,evidence,agents,causal,decision,story,feedback}/
    -> data/processed/*.parquet, data/evidence/*, data/feedback/*.jsonl, config/*.yaml
```

See `API_ARCHITECTURE.md` for the endpoint-to-engine-call table and `FRONTEND_BACKEND_INTEGRATION.md` for the frontend-side mapping. See `SECURITY_ARCHITECTURE.md` for the RBAC/clearance design.

## What is real vs. fallback/demo

- **Real, live**: every `causa/api/routes/*.py` handler calls a real engine function against real canonical Parquet data (`data/processed/`) and real governed config (`config/*.yaml`). No hardcoded business numbers anywhere in `causa/api/`.
- **Real, replayed**: `POST /api/investigations` for the exact Revenue/November-2017 scenario replays `causa/reports/step5_validation.json` — a real, previously-validated orchestrator run (not fabricated, not mocked; see `causa/PROJECT_JOURNEY.md`'s note on the most recent live Groq re-run).
- **Fallback/demo, explicit**: `frontend/src/api/demoAdapter/` and `frontend/public/fixtures/*.json` remain in the repo, untouched, as an explicit offline/testing fallback. `frontend/src/api/index.ts` is the single one-line switch between `./productionApi` (current) and `./demoAdapter`.

## State ownership

- Canonical KPI/evidence engine state: owned by `causa/api/bootstrap.py`'s single process-lifetime `EngineBundle` (registry, KPIEngine, ToolContext) — read-only by convention, rebuilt only on process restart.
- Investigation lifecycle state: owned by `causa/api/store.py`'s `InvestigationStore` — in-memory dict, mirrored to `causa/data/investigations/{id}.json` (gitignored, regenerable).
- Feedback state: owned by the pre-existing `src/feedback/store.py::FeedbackStore` (append-only JSONL under `data/feedback/`), reused as-is.

## Error handling

`causa/api/errors.py` maps every real, already-documented engine exception (`DriverRequestError`, `UnauthorizedSegmentError`, `UnsupportedFilterError`, `ReconciliationError`, `BudgetExceeded`, `InvalidFeedbackError`, `InvalidTransitionError`, ...) to an HTTP status and a redacted JSON error envelope (`evidence.access_control.redact_error_message`), so a client below INTERNAL clearance never sees a raw identifier-shaped token in an error message, and no path returns a bare Python traceback.

## Security boundaries

See `SECURITY_ARCHITECTURE.md`. Summary: the browser sends a role NAME only; the server is the only place that resolves a role to a `SecurityClassification` clearance (via `src/tools/policy.py`, never a parallel policy), and every evidence/graph/segment-returning route filters through `src/evidence/access_control.py`/`drivers.engine`'s own clearance checks.
