import { useQuery } from '@tanstack/react-query'
import {
  getContradictionChecks,
  getEvidenceById,
  getEvidenceGraph,
  getReviewCorpusStats,
  getReviewEvidenceSamples,
  getStructuredEvidence,
} from '@/api'

export function useStructuredEvidence() {
  return useQuery({ queryKey: ['evidence-structured'], queryFn: getStructuredEvidence })
}

export function useReviewEvidence() {
  return useQuery({ queryKey: ['evidence-reviews'], queryFn: getReviewEvidenceSamples })
}

export function useEvidenceById(id: string | null) {
  return useQuery({ queryKey: ['evidence', id], queryFn: () => getEvidenceById(id as string), enabled: !!id })
}

export function useContradictionChecks() {
  return useQuery({ queryKey: ['contradiction-checks'], queryFn: getContradictionChecks })
}

export function useReviewCorpusStats() {
  return useQuery({ queryKey: ['review-corpus-stats'], queryFn: getReviewCorpusStats })
}

export function useEvidenceGraph() {
  return useQuery({ queryKey: ['evidence-graph'], queryFn: getEvidenceGraph })
}
