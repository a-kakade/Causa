import { apiFetch } from './client'

export interface FeedbackCaseView {
  key: string
  feedbackId: string
  rating: 'CORRECT' | 'PARTIALLY_CORRECT' | 'INCORRECT'
  categories: string[]
  summary: string
  caseId?: string
  testId?: string
  regressionCaught: boolean
  failureReasons: string[]
}

export async function getFeedbackSummary() {
  const r = await apiFetch<{ count: number; feedback: Array<{ status: string; review_status: string }> }>('/api/feedback')
  return {
    total_feedback: r.count,
    total_corrections: 0,
    total_business_contexts: 0,
    total_evaluation_cases: (await apiFetch<{ count: number }>('/api/learning/evaluation-cases')).count,
    total_regression_tests: (await apiFetch<{ count: number }>('/api/learning/regressions')).count,
  }
}

const RATING_MAP: Record<string, 'CORRECT' | 'PARTIALLY_CORRECT' | 'INCORRECT'> = {
  CORRECT: 'CORRECT', WRONG_CONFIDENCE: 'PARTIALLY_CORRECT', MISSING_DRIVER: 'PARTIALLY_CORRECT',
  INCORRECT: 'INCORRECT', WRONG_RECOMMENDATION: 'INCORRECT', COMMENT_ONLY: 'PARTIALLY_CORRECT',
}

export async function getFeedbackCases(): Promise<FeedbackCaseView[]> {
  const r = await apiFetch<{ feedback: Array<{ feedback_id: string; rating: string; categories: string[]; comment: string | null }> }>('/api/feedback')
  return r.feedback.map((f) => ({
    key: f.feedback_id, feedbackId: f.feedback_id, rating: RATING_MAP[f.rating] ?? 'PARTIALLY_CORRECT',
    categories: f.categories, summary: f.comment ?? '', regressionCaught: false, failureReasons: [],
  }))
}

export async function getRegressionComparison() {
  // src/feedback/evaluator.py's compare_baseline_candidate is an on-demand
  // function, not a persisted run log (see routes/feedback.py's
  // /api/learning/evaluations docstring) -- report that honestly.
  return {
    baseline_metrics: {} as Record<string, number>, candidate_metrics: {} as Record<string, number>,
    deltas: {} as Record<string, number>, regressions: [] as string[], improvements: [] as string[],
    note: 'No offline evaluation run has been executed against a stored dataset_version yet in this session.',
  }
}
