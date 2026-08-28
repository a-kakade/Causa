import { loadFixture } from './loadFixture'

interface RawCase {
  feedback_id: string
  categories?: string[]
  case_id?: string
  test_id?: string
  good_report?: unknown
  regression_bad_report?: {
    total: number
    passed: number
    failed: number
    results: { test_id: string; case_id: string; passed: boolean; failure_reasons: string[] }[]
  }
}

interface Step9Report {
  feedback_summary: {
    total_feedback: number
    total_corrections: number
    total_business_contexts: number
    total_evaluation_cases: number
    total_regression_tests: number
  }
  cases: Record<string, RawCase>
  dataset_level_evaluation: {
    baseline: { total_cases: number; passed: number; failed: number; metrics: Record<string, number> }
    candidate: { total_cases: number; passed: number; failed: number; metrics: Record<string, number> }
    comparison: {
      baseline_metrics: Record<string, number>
      candidate_metrics: Record<string, number>
      deltas: Record<string, number>
      regressions: string[]
      improvements: string[]
    }
  }
}

const CASE_LABELS: Record<string, { rating: 'CORRECT' | 'PARTIALLY_CORRECT' | 'INCORRECT'; summary: string }> = {
  case1_correct: { rating: 'CORRECT', summary: 'Investigation conclusion matched reviewer judgment — no correction needed.' },
  case2_wrong_driver: { rating: 'INCORRECT', summary: 'Wrong driver attributed — reviewer corrected the claimed cause of the review-score movement.' },
  case3_wrong_recommendation: { rating: 'INCORRECT', summary: 'Recommended action did not match the actual controllable lever.' },
  case4_wrong_confidence: { rating: 'PARTIALLY_CORRECT', summary: 'Confidence level overstated relative to the evidence actually retrieved.' },
  case5_missing_driver: { rating: 'PARTIALLY_CORRECT', summary: 'A material driver was omitted from the investigation.' },
}

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

let cached: Step9Report | null = null
async function report(): Promise<Step9Report> {
  if (!cached) cached = await loadFixture<Step9Report>('step9_validation')
  return cached
}

export async function getFeedbackSummary() {
  const r = await report()
  return r.feedback_summary
}

export async function getFeedbackCases(): Promise<FeedbackCaseView[]> {
  const r = await report()
  return Object.entries(r.cases).map(([key, c]) => {
    const label = CASE_LABELS[key] ?? { rating: 'PARTIALLY_CORRECT' as const, summary: '' }
    const failed = c.regression_bad_report?.results.flatMap((res) => res.failure_reasons) ?? []
    return {
      key,
      feedbackId: c.feedback_id,
      rating: label.rating,
      categories: c.categories ?? [],
      summary: label.summary,
      caseId: c.case_id,
      testId: c.test_id,
      regressionCaught: (c.regression_bad_report?.failed ?? 0) > 0,
      failureReasons: failed,
    }
  })
}

export async function getRegressionComparison() {
  const r = await report()
  return r.dataset_level_evaluation.comparison
}
