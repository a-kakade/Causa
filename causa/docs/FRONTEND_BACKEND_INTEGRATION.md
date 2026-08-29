# Frontend ↔ Backend Integration

## The swap

`frontend/src/api/index.ts` is the single seam:

```ts
export * from './productionApi'   // current
// export * from './demoAdapter'  // offline/testing fallback
```

`frontend/src/api/productionApi/` mirrors `demoAdapter/`'s file-per-domain layout and exported function names 1:1 (`kpiRegistry.ts`, `kpis.ts`, `kpiTimeseries.ts`, `drivers.ts`, `evidence.ts`, `evidenceGraph.ts`, `investigations.ts`, `causal.ts`, `decisions.ts`, `narrative.ts`, `security.ts`, `telemetry.ts`, `logs.ts`, `feedback.ts`), sourcing data via a new `client.ts` (`apiFetch`/`apiPost` against `VITE_API_BASE_URL`, `?requester_role=` attached automatically) instead of `loadFixture`.

`frontend/.env` / `.env.example`: `VITE_API_BASE_URL=http://localhost:8000`.

## Import-path fix (prerequisite)

11 files imported directly from `@/api/demoAdapter/*` submodules instead of the `@/api` barrel, which would have broken the one-line-swap property. Fixed as a standalone change before the swap:

`pages/LogsPage.tsx`, `pages/SecurityPage.tsx`, `pages/InvestigatePage.tsx`, `pages/OverviewPage.tsx`, `hooks/useDrivers.ts`, `components/evidence/EvidenceGraph.tsx`, `components/investigation/ConcurrentKpiPanel.tsx`, `components/security/PromptInjectionDemo.tsx`, `components/security/RBACPanel.tsx`, `components/kpi/KPIStrip.tsx`, `components/kpi/KPITrend.tsx`.

## Shape differences from the demo adapter (documented, not hidden)

1. **`getInvestigation(role)`** keeps its signature (no call-site changes) by calling `GET /api/investigations?role=&latest=true` — "most recent investigation created under this role" — and auto-creating one (`POST /api/investigations`, canonical Nov-2017 scenario) if none exists yet for that role. This preserves the frontend's "one canned investigation per role" mental model while the real backend is investigation-id-keyed underneath.
2. **`DecisionKey` (`'delivery_delay' | 'aov_decline'`)** was a fixed pair of demo-script scenarios in the old fixture; the real API's recommendations are investigation-scoped. Both keys currently resolve to the same (Analyst-role) investigation's recommendations. A richer investigation picker in the UI is the natural next step to make this a real distinction again — flagged as remaining work.
3. **`getSyntheticMethodDemonstrations()` / evidence-package-items** have no real backend equivalent (they were demo-script-only concepts) — return an honestly-empty result rather than fabricating one.
4. **`getSecurityPolicy`/`RBAC_CLEARANCE_FOR_ROLE`/`ALLOWED_TOOLS_PER_AGENT`** are now fetched once from `GET /api/security/policy` (real `src/tools/policy.py` tables) and merged into the same exported constants on first resolution, so existing call sites keep working without an async refactor.
5. **Telemetry/logs/audit** now read from `GET /api/investigations/{id}/telemetry` and `GET /api/audit` respectively — real per-investigation and cross-investigation data, with `telemetry_available: false` surfaced explicitly instead of a fabricated zero when nothing was measured.

## RBAC on the client

The client (`AppStateContext`'s `requesterRole`, wired into `client.ts` via `setApiRequesterRole`) sends a **role name only**. It never sends or receives a raw clearance value from the browser — the server derives clearance from the role name via `src/tools/policy.py` and enforces it on every evidence/segment/graph response. Toggling role in the UI genuinely changes what data comes back (verified: EXECUTIVE sees 383 evidence items vs. ANALYST's 12,216 on the same `/api/evidence` call, live).

## Fallback mode

`demoAdapter/` and `frontend/public/fixtures/*.json` are untouched and remain a fully working, zero-backend fallback — flip `api/index.ts` back to `export * from './demoAdapter'` to use them (e.g. for offline development or a static hosting demo with no Python backend running).
