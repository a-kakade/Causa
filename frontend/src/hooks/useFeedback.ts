import { useQuery } from '@tanstack/react-query'
import { getFeedbackCases, getFeedbackSummary, getRegressionComparison } from '@/api'

export function useFeedbackCases() {
  return useQuery({ queryKey: ['feedback-cases'], queryFn: getFeedbackCases })
}

export function useFeedbackSummary() {
  return useQuery({ queryKey: ['feedback-summary'], queryFn: getFeedbackSummary })
}

export function useRegressionComparison() {
  return useQuery({ queryKey: ['regression-comparison'], queryFn: getRegressionComparison })
}
