# API Architecture

## Structure

```
causa/api/
  main.py            FastAPI() app, CORS, lifespan (builds the engine bundle once), router includes
  config.py          ApiSettings (plain env vars: host/port/CORS origins)
  bootstrap.py        EngineBundle: SemanticRegistry, KPIEngine, ToolContext -- built once, cached
  dependencies.py      get_engine_bundle, get_investigation_store, get_requester_role, get_requester_clearance
  store.py             InvestigationStore / InvestigationRecord -- in-memory + JSON-file mirror
  serializers.py        dataclass/Pydantic -> JSON dict adapters (thin, calls .to_dict()/.model_dump())
  kpi_support.py         shared AnomalyRequest-baseline-building helper (mirrors evidence/engine.py's own pattern)
  errors.py               exception -> HTTP response translation, clearance-aware redaction
  routes/
    health.py, overview.py, kpis.py, drivers.py, investigations.py, evidence.py,
    causal.py, decisions.py, story.py, feedback.py, audit.py, security.py, telemetry.py
```

Every route handler is a thin controller: resolve role/clearance (`dependencies.py`) -> call a real function in `causa/src/` -> serialize -> return. **No file under `causa/src/` was modified.**

## Bootstrap / engine bundle lifecycle

`bootstrap.get_bundle()` builds, once, at process startup (`main.py`'s `lifespan`):
1. `SemanticRegistry.load().validate()`
2. `KPIEngine(registry=registry)` (lazily loads `data/processed/*.parquet` on first table access)
3. `tools.context.build_tool_context(canonical, kpi_engine, registry)` — the same Step 4 evidence package + BM25/vector index build `scripts/step5_investigate_november_2017.py` already performs.

Cost: ~1-2 minutes (parquet load + embedding model load + review-corpus embedding). This is a **known limitation**: the bundle is a single-process, in-memory singleton — not safe to run with multiple uvicorn workers (each worker would rebuild its own bundle and hold its own `ToolContext.evidence_store`, which also grows as tools run). Fine for this prototype's single-process deployment; documented here rather than hidden.

## Endpoint -> engine call table

| Endpoint | Engine call(s) | Notes |
|---|---|---|
| `GET /api/health` | `bootstrap.is_ready()` | liveness only |
| `GET /api/overview` | `KPIEngine.compare_periods` (×N), `anomaly.engine.detect`, `drivers.engine.decompose` | the one new aggregation — no single Step function returns "everything for the overview page" |
| `GET /api/kpis`, `/{id}`, `/{id}/timeseries` | `KPIEngine.compare_periods` / `.compute` | |
| `GET /api/kpis/{id}/drivers|pvm|segments|concurrent` | `drivers.engine.decompose` | clearance passed straight through; engine raises `Unauthorized/UnsupportedSegmentError` |
| `POST/GET /api/investigations[/{id}]`, `/hypotheses`, `/process` | `agents.orchestrator.run_investigation` (or a replay of `reports/step5_validation.json`) | see trigger policy below |
| `GET /api/evidence[/{id}]`, `/graph/full`, `/search/reviews`, `/contradictions/checks` | `evidence.access_control.filter_evidence_objects/filter_graph`, `evidence.retrieval.retrieve` | clearance-filtered |
| `GET /api/investigations/{id}/causal-analysis` | `causal.engine.causal_hypothesis_from_step5` + `run_causal_analysis` | lazy, cached |
| `GET /api/investigations/{id}/recommendations` | `decision.bridge.driver_signal_from_hypothesis_result` + `decision.ranking.run_decision_pipeline` | lazy, cached |
| `GET /api/investigations/{id}/story` | `story.evidence_package.build_evidence_package` + `story.engine.generate_kpi_story` | lazy, cached, per persona |
| `POST/GET /api/feedback[/{id}]`, `/review`, `/api/learning/*` | `src/feedback/*` + `FeedbackStore` | the only pre-existing durable store, reused as-is |
| `GET /api/audit`, `/api/investigations/{id}/audit` | `state.audit_trace` + `state.security_events` | strict field allowlist, never raw LLM I/O |
| `GET /api/security/policy`, `/rbac-demo`, `/prompt-injection-demo` | `src/tools/policy.py`, `src/agents/security.py` | reads/exercises the real policy, never redefines it |
| `GET /api/telemetry`, `/api/investigations/{id}/telemetry` | `agents.telemetry.aggregate` | missing data -> `null` + `telemetry_available: false`, never `0` |

## Investigation trigger policy (`routes/investigations.py`)

`POST /api/investigations` with `{kpi_id, period_current, period_previous, mode}`:

1. **`mode="auto"` + `(kpi_id, period_current, period_previous) == ("revenue", "2017-11", "2017-10")`** → replay `causa/reports/step5_validation.json` (`source: "replay"`). Free, deterministic, and is the already-independently-validated real run this whole repo's documentation centers on. Falls back to (2) if the report file doesn't exist yet on a fresh checkout.
2. **`mode="auto"`, any other KPI/period** → a real, synchronous `agents.orchestrator.run_investigation()` call using `_ApiScriptedClient` (`source: "fake_llm"`) — a generalized version of `scripts/step5_investigate_november_2017.py::DryRunScriptedClient`: the model's hypothesis *text* is scripted, but every tool call goes through the real Tool Gateway against real data for the requested `kpi_id`. Free, fast, and will honestly reach `ABSTAINED`/`NEEDS_CLARIFICATION` if the evidence doesn't support a conclusion.
3. **`mode="live"`** → a real Groq call (`agents.llm_client.GroqLLMClient`, `source: "live_llm"`), only if `has_groq_credentials()` is true; 400 otherwise.

`GET /api/investigations/{id}/causal-analysis|recommendations|story` are computed **lazily on first request** and cached on the `InvestigationRecord` (`causa/api/store.py`) — not eagerly at creation, so creating an investigation stays fast and Steps 6-8 only run for investigations someone actually drills into.

## `/process` (Phase 8 "process proof")

`run_investigation()` is atomic — it runs the full state machine to a terminal status in one call and is not steppable. `GET /api/investigations/{id}/process` therefore returns the completed run's `status_history` + `audit_trace` (a reconstruction of the process trace), not a live-polled incremental status. This is a deliberate, documented scope decision, not an oversight.

## Known limitations

- Single-process only (see bootstrap section above).
- No background job queue — `mode=live`/`fake_llm` investigation creation is a synchronous request; a slow LLM call blocks that one request (acceptable for a prototype demo, not for production scale).
- `/process` is derived, not live-stepped (see above).
- No persisted log of past offline-evaluation runs (`GET /api/learning/evaluations` returns `runs: []` honestly rather than fabricating history — see `src/feedback/evaluator.py`'s own docstring: it's an on-demand function, not a durable table).
