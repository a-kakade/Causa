/**
 * kpiRegistry.ts (productionApi) — the KPI catalog's cosmetic metadata
 * (name/description/unit/classification) is UI labeling, not governed
 * business data, so it is kept as the same static, hand-ported table the
 * demo adapter uses (itself hand-ported from config/kpis.yaml) rather than
 * fetched — no engine call computes "what is Revenue's unit". Every actual
 * VALUE for a KPI still comes from a real API call in kpis.ts/kpiTimeseries.ts.
 */
export { KPI_REGISTRY, kpiDef, DEMO_PERIOD_CURRENT, DEMO_PERIOD_PREVIOUS } from '../demoAdapter/kpiRegistry'
