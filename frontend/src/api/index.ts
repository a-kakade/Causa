// The runtime Live/Demo switch (see api/mode.ts): every data function below
// dispatches to productionApi (the real FastAPI backend) or demoAdapter (the
// offline, fixture-backed adapter used before the backend existed) based on
// getApiMode(). Every page/hook imports data functions from `@/api`, never
// from either adapter directly, so switching modes never requires touching
// call sites. The two adapters share the same exported function surface by
// design (see productionApi/index.ts's own comment) -- this file is the one
// place that surface is actually dispatched rather than statically re-exported.
import * as demo from './demoAdapter'
import * as prod from './productionApi'
import { getApiMode } from './mode'

export { getApiMode, setApiMode, subscribeApiMode } from './mode'
export type { ApiMode } from './mode'

// Cosmetic/static catalogs (KPI names/units, RBAC tables, tool registry) are
// hand-ported the same way in both adapters -- no dispatch needed.
export { KPI_REGISTRY, kpiDef, DEMO_PERIOD_CURRENT, DEMO_PERIOD_PREVIOUS } from './productionApi/kpiRegistry'
export { filterLogs, type LogEntry, type LogFilters } from './productionApi/logs'
export { setApiPeriod, setApiRequesterRole } from './productionApi/client'
export type { EvidenceGraphData, LaidOutNode } from './productionApi/evidenceGraph'
export type { DecisionKey } from './productionApi/decisions'
export type { TelemetrySummary, AskQuestionResult } from './productionApi/investigations'
export type { FeedbackCaseView } from './productionApi/feedback'
export type { MonthlyPoint } from './productionApi/kpiTimeseries'
export type { AgentMetric, TelemetryView } from './productionApi/telemetry'

function route<A extends unknown[], R>(prodFn: (...a: A) => R, demoFn: (...a: A) => R) {
  return (...args: A): R => (getApiMode() === 'demo' ? demoFn(...args) : prodFn(...args))
}

// kpis.ts
export const getKpiMovements = route(prod.getKpiMovements, demo.getKpiMovements)
export const getKpiMovement = route(prod.getKpiMovement, demo.getKpiMovement)

// kpiTimeseries.ts
export const getMonthlyKpiTimeseries = route(prod.getMonthlyKpiTimeseries, demo.getMonthlyKpiTimeseries)
export const getKpiTrendSeries = route(prod.getKpiTrendSeries, demo.getKpiTrendSeries)

// drivers.ts
export const getPVM = route(prod.getPVM, demo.getPVM)
export const getDriverContributions = route(prod.getDriverContributions, demo.getDriverContributions)
export const getSegmentContributions = route(prod.getSegmentContributions, demo.getSegmentContributions)
export const getConcurrentKpiMovements = route(prod.getConcurrentKpiMovements, demo.getConcurrentKpiMovements)
export const getDriverDecomposition = route(prod.getDriverDecomposition, demo.getDriverDecomposition)
export const RESTRICTED_DIMENSIONS = prod.RESTRICTED_DIMENSIONS

// evidence.ts
export const getStructuredEvidence = route(prod.getStructuredEvidence, demo.getStructuredEvidence)
export const getEvidenceById = route(prod.getEvidenceById, demo.getEvidenceById)
export const getReviewEvidenceSamples = route(prod.getReviewEvidenceSamples, demo.getReviewEvidenceSamples)
export const getRetrievalBuckets = route(prod.getRetrievalBuckets, demo.getRetrievalBuckets)
export const getContradictionChecks = route(prod.getContradictionChecks, demo.getContradictionChecks)
export const getEvidenceGraphSummary = route(prod.getEvidenceGraphSummary, demo.getEvidenceGraphSummary)
export const getReviewCorpusStats = route(prod.getReviewCorpusStats, demo.getReviewCorpusStats)

// evidenceGraph.ts
export const getEvidenceGraph = route(prod.getEvidenceGraph, demo.getEvidenceGraph)

// investigations.ts
export const createInvestigation = route(prod.createInvestigation, demo.createInvestigation)
export const getInvestigation = route(prod.getInvestigation, demo.getInvestigation)
export const getCurrentInvestigationId = route(prod.getCurrentInvestigationId, demo.getCurrentInvestigationId)
export const getTelemetrySummary = route(prod.getTelemetrySummary, demo.getTelemetrySummary)
export const askInvestigationQuestion = route(prod.askInvestigationQuestion, demo.askInvestigationQuestion)
export const getRunMeta = route(prod.getRunMeta, demo.getRunMeta)

// causal.ts
export const getCausalResults = route(prod.getCausalResults, demo.getCausalResults)
export const getCausalResult = route(prod.getCausalResult, demo.getCausalResult)
export const getSyntheticMethodDemonstrations = route(prod.getSyntheticMethodDemonstrations, demo.getSyntheticMethodDemonstrations)
export const getCausalHonestAbstentionNote = route(prod.getCausalHonestAbstentionNote, demo.getCausalHonestAbstentionNote)
export const getCausalGraphSummary = route(prod.getCausalGraphSummary, demo.getCausalGraphSummary)

// decisions.ts
export const getDecisionResult = route(prod.getDecisionResult, demo.getDecisionResult)
export const getAllDecisionResults = route(prod.getAllDecisionResults, demo.getAllDecisionResults)
export const getDecisionNarrative = route(prod.getDecisionNarrative, demo.getDecisionNarrative)

// narrative.ts
export const getStory = route(prod.getStory, demo.getStory)
export const getAllStories = route(prod.getAllStories, demo.getAllStories)
export const getEvidencePackageItems = route(prod.getEvidencePackageItems, demo.getEvidencePackageItems)
export const getEvidencePackageMeta = route(prod.getEvidencePackageMeta, demo.getEvidencePackageMeta)

// security.ts -- constants are hand-ported identically in both adapters;
// productionApi's copies are refreshed from the real server policy shortly
// after load (see productionApi/security.ts), which is fine in Live mode
// and simply never fires a request worth caring about in Demo mode.
export const RBAC_CLEARANCE_FOR_ROLE = prod.RBAC_CLEARANCE_FOR_ROLE
export const CLEARANCE_RANK = prod.CLEARANCE_RANK
export const ALLOWED_TOOLS_PER_AGENT = prod.ALLOWED_TOOLS_PER_AGENT
export const TOOL_REGISTRY = prod.TOOL_REGISTRY
export const getPromptInjectionFixtures = route(prod.getPromptInjectionFixtures, demo.getPromptInjectionFixtures)
// runPromptInjectionDemo is async in productionApi (a real server round trip)
// and sync in demoAdapter (a local regex classifier) -- normalize to async
// so call sites never need to know which mode is active.
export const runPromptInjectionDemo = route(
  prod.runPromptInjectionDemo,
  async (...a: Parameters<typeof demo.runPromptInjectionDemo>) => demo.runPromptInjectionDemo(...a),
)
export const runRbacDemo = route(prod.runRbacDemo, demo.runRbacDemo)

// telemetry.ts
export const getTelemetryView = route(prod.getTelemetryView, demo.getTelemetryView)

// logs.ts
export const getAllLogs = route(prod.getAllLogs, demo.getAllLogs)

// feedback.ts
export const getFeedbackSummary = route(prod.getFeedbackSummary, demo.getFeedbackSummary)
export const getFeedbackCases = route(prod.getFeedbackCases, demo.getFeedbackCases)
export const getRegressionComparison = route(prod.getRegressionComparison, demo.getRegressionComparison)
