/** Mirrors src/feedback/models.py — Step 9 Human Feedback & Learning Loop. */

export type FeedbackRating = 'CORRECT' | 'PARTIALLY_CORRECT' | 'INCORRECT'

export type FeedbackCategory = 'DATA' | 'KPI_DEFINITION' | 'DRIVER' | 'EVIDENCE' | 'CONFIDENCE' | 'RECOMMENDATION' | 'NARRATIVE'

export type FeedbackStatus = 'UNREVIEWED' | 'ACCEPTED' | 'REJECTED' | 'CONTESTED'

export interface Feedback {
  feedbackId: string
  investigationId: string
  rating: FeedbackRating
  categories: FeedbackCategory[]
  comment: string | null
  status: FeedbackStatus
  submittedAt: string
  submittedBy: string
}

export interface Outcome {
  actionId: string
  driver: string
  owner: string
  predictedImpact: number
  actualImpact: number | null
  metric: string
  status: 'MONITORING' | 'CONFIRMED' | 'INCONCLUSIVE' | 'REVERSED'
  confidence: string
  windowLabel: string
}
