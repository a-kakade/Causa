import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { Badge } from '@/components/common/Badge'
import { TrustBadge } from './TrustBadge'
import { formatDateTime } from '@/lib/format'
import type { EvidenceObject } from '@/types/evidence'

export function EvidenceCard({ evidence, onOpen }: { evidence: EvidenceObject; onOpen?: () => void }) {
  const isReview = evidence.evidenceType === 'CUSTOMER_REVIEW'
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full rounded-(--radius-md) border border-(--color-border) p-3 text-left transition-colors hover:border-(--color-accent-border) hover:bg-(--color-surface-2)"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] font-semibold text-(--color-ink-faint)">{evidence.evidenceId}</span>
        <div className="flex items-center gap-1.5">
          <Badge tone="neutral">{evidence.evidenceTier.replace('_', ' ')}</Badge>
          <TrustBadge level={evidence.security.trustLevel} />
        </div>
      </div>

      {isReview && evidence.content ? (
        <p className="mt-1.5 text-[13px] italic leading-snug text-(--color-ink)">“{evidence.content}”</p>
      ) : (
        <p className="mt-1.5 text-[13px] leading-snug text-(--color-ink)">{evidence.claim}</p>
      )}

      <div className="mt-2 flex items-center justify-between text-[11px] text-(--color-ink-faint)">
        <span>{evidence.source.system}</span>
        <div className="flex items-center gap-2">
          <ConfidenceBadge level={evidence.confidence} size="sm" />
          <span>{formatDateTime(evidence.createdAt)}</span>
        </div>
      </div>
    </button>
  )
}
