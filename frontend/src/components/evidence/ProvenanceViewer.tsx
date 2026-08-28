import { Drawer } from '@/components/common/Drawer'
import { Badge } from '@/components/common/Badge'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { TrustBadge } from './TrustBadge'
import { formatDateTime } from '@/lib/format'
import type { EvidenceObject } from '@/types/evidence'

export function ProvenanceViewer({ evidence, onClose }: { evidence: EvidenceObject | null; onClose: () => void }) {
  return (
    <Drawer open={!!evidence} onOpenChange={(o) => !o && onClose()} title={evidence?.evidenceId ?? ''} subtitle={evidence?.evidenceType} width="lg">
      {evidence ? (
        <div className="space-y-5">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Claim</p>
            <p className="mt-1 text-[13px] leading-relaxed text-(--color-ink)">{evidence.content ? `"${evidence.content}"` : evidence.claim}</p>
          </div>

          <div className="flex flex-wrap gap-1.5">
            <Badge tone="neutral">{evidence.evidenceTier.replace('_', ' ')}</Badge>
            <Badge tone="neutral">{evidence.evidenceType.replaceAll('_', ' ')}</Badge>
            <ConfidenceBadge level={evidence.confidence} size="sm" />
            <TrustBadge level={evidence.security.trustLevel} />
            <Badge tone="neutral">{evidence.security.classification}</Badge>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Computed by</p>
            <p className="mt-1 text-[13px] text-(--color-ink)">{evidence.source.system}</p>
            <p className="font-mono text-[11px] text-(--color-ink-faint)">{evidence.source.component} · v{evidence.source.version}</p>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Period</p>
            <p className="mt-1 text-[13px] text-(--color-ink)">
              {evidence.time.start} → {evidence.time.end}
            </p>
          </div>

          {evidence.retrieval ? (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Retrieval</p>
              <p className="mt-1 text-[13px] text-(--color-ink)">
                rank {evidence.retrieval.rank} · score {evidence.retrieval.score.toFixed(3)}
              </p>
              <p className="font-mono text-[11px] text-(--color-ink-faint)">{evidence.retrieval.method}</p>
            </div>
          ) : null}

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Quality</p>
            <div className="mt-1 grid grid-cols-2 gap-1.5">
              {Object.entries(evidence.quality)
                .filter(([, v]) => v !== null)
                .map(([k, v]) => (
                  <div key={k} className="rounded-(--radius-sm) bg-(--color-surface-2) px-2 py-1">
                    <p className="text-[10px] uppercase text-(--color-ink-faint)">{k}</p>
                    <p className="font-mono text-[12px] font-semibold text-(--color-ink)">{typeof v === 'number' ? v.toFixed(2) : String(v)}</p>
                  </div>
                ))}
            </div>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Lineage</p>
            <ol className="mt-1.5 space-y-1.5">
              {evidence.lineage.map((l, i) => (
                <li key={i} className="flex items-center gap-2 text-[12px]">
                  <span className="rounded-(--radius-xs) bg-(--color-surface-2) px-1.5 py-0.5 font-mono text-[10px] uppercase text-(--color-ink-faint)">
                    {l.layer}
                  </span>
                  <span className="font-mono text-(--color-ink-muted)">{l.reference}</span>
                </li>
              ))}
            </ol>
          </div>

          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Created</p>
            <p className="mt-1 font-mono text-[12px] text-(--color-ink-muted)">{formatDateTime(evidence.createdAt)}</p>
          </div>
        </div>
      ) : null}
    </Drawer>
  )
}
