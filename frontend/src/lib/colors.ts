import type { ConfidenceLevel } from '@/types/common'

/** The one place confidence -> color is decided. Never call this with a
 * fabricated level — always pass the backend's actual ConfidenceLevel. */
export function confidenceTone(level: ConfidenceLevel | null | undefined): {
  fg: string
  bg: string
  dot: string
  label: string
} {
  switch (level) {
    case 'HIGH':
      return { fg: 'text-(--color-confidence-high)', bg: 'bg-(--color-confidence-high-soft)', dot: 'bg-(--color-confidence-high)', label: 'HIGH' }
    case 'MEDIUM':
      return { fg: 'text-(--color-confidence-medium)', bg: 'bg-(--color-confidence-medium-soft)', dot: 'bg-(--color-confidence-medium)', label: 'MEDIUM' }
    case 'LOW':
      return { fg: 'text-(--color-confidence-low)', bg: 'bg-(--color-confidence-low-soft)', dot: 'bg-(--color-confidence-low)', label: 'LOW' }
    case 'NEEDS_CLARIFICATION':
      return {
        fg: 'text-(--color-confidence-abstain)',
        bg: 'bg-(--color-confidence-abstain-soft)',
        dot: 'bg-(--color-confidence-abstain)',
        label: 'NEEDS CLARIFICATION',
      }
    case 'ABSTAIN':
      return { fg: 'text-(--color-confidence-abstain)', bg: 'bg-(--color-confidence-abstain-soft)', dot: 'bg-(--color-confidence-abstain)', label: 'ABSTAIN' }
    default:
      return { fg: 'text-(--color-ink-faint)', bg: 'bg-(--color-neutral-soft)', dot: 'bg-(--color-neutral)', label: 'UNKNOWN' }
  }
}

export function materialityTone(m: string): { fg: string; bg: string } {
  switch (m) {
    case 'CRITICAL':
      return { fg: 'text-(--color-negative)', bg: 'bg-(--color-negative-soft)' }
    case 'MATERIAL':
      return { fg: 'text-(--color-warning)', bg: 'bg-(--color-warning-soft)' }
    case 'WATCH':
      return { fg: 'text-(--color-warning)', bg: 'bg-(--color-warning-soft)' }
    case 'NORMAL':
      return { fg: 'text-(--color-neutral)', bg: 'bg-(--color-neutral-soft)' }
    default:
      return { fg: 'text-(--color-ink-faint)', bg: 'bg-(--color-neutral-soft)' }
  }
}

export function directionTone(direction: 'up' | 'down' | 'flat', favorable: boolean): string {
  if (direction === 'flat') return 'text-(--color-ink-faint)'
  return favorable ? 'text-(--color-positive)' : 'text-(--color-negative)'
}
