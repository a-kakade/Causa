/**
 * PRODUCTION API — the real HTTP-backed adapter, matching demoAdapter's
 * exported function surface 1:1 so `src/api/index.ts` can be a one-line
 * swap. See docs/FRONTEND_BACKEND_INTEGRATION.md for the full mapping.
 */
export const DEMO_MODE = false

export * from './client'
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
