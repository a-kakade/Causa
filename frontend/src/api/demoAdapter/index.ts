/**
 * DEMO ADAPTER — the single data source for this build.
 *
 * Every export here reads a static copy of a real, backend-computed
 * validation report (see /public/fixtures and causa/reports/*.json).
 * Nothing is hand-authored. See docs/FRONTEND_ARCHITECTURE.md and
 * docs/UI_DATA_FLOW.md for the full mapping from fixture -> adapter -> hook
 * -> component.
 *
 * `productionApi/` is the seam for a future real HTTP API — when one
 * exists, `src/api/index.ts` is the only file that needs to change.
 */
export { DEMO_MODE } from './loadFixture'
export * from './kpiRegistry'
export * from './kpis'
export * from './kpiTimeseries'
export * from './drivers'
export * from './evidence'
export * from './evidenceGraph'
export * from './investigations'
export * from './causal'
export * from './decisions'
export * from './narrative'
export * from './security'
export * from './telemetry'
export * from './logs'
export * from './feedback'
