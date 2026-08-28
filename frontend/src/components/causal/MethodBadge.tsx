import { Badge } from '@/components/common/Badge'
import type { CausalMethod, CausalTier } from '@/types/causal'

const TIER_LABEL: Record<CausalTier, string> = {
  T1_DESCRIPTIVE: 'T1 · Descriptive',
  T2_ARITHMETIC: 'T2 · Arithmetic',
  T3_QUASI_EXPERIMENTAL: 'T3 · Quasi-experimental',
  T4_EXPERIMENTAL: 'T4 · Experimental',
}

export function TierBadge({ tier }: { tier: CausalTier }) {
  const tone = tier === 'T3_QUASI_EXPERIMENTAL' || tier === 'T4_EXPERIMENTAL' ? 'accent' : 'neutral'
  return <Badge tone={tone}>{TIER_LABEL[tier]}</Badge>
}

export function MethodBadge({ method }: { method: CausalMethod }) {
  return <Badge tone="neutral">{method.replaceAll('_', ' ')}</Badge>
}
