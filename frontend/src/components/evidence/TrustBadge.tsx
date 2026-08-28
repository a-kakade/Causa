import { ShieldCheck, ShieldOff } from 'lucide-react'
import type { TrustLevel } from '@/types/common'

/** Spec §28: visually distinguish TRUSTED SYSTEM EVIDENCE from UNTRUSTED
 * SOURCE TEXT. This is the one place that distinction is drawn. */
export function TrustBadge({ level }: { level: TrustLevel }) {
  if (level === 'UNTRUSTED_DATA') {
    return (
      <span className="inline-flex items-center gap-1 rounded-(--radius-xs) border border-dashed border-(--color-warning) bg-(--color-warning-soft) px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-(--color-warning)">
        <ShieldOff className="size-3" /> Untrusted data
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-(--radius-xs) bg-(--color-neutral-soft) px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-(--color-ink-muted)">
      <ShieldCheck className="size-3" /> Trusted system
    </span>
  )
}
