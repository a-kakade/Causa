import type { ConfidenceLevel } from '@/types/common'
import { cn } from '@/lib/cn'
import { confidenceTone } from '@/lib/colors'

/**
 * The one place a confidence level is rendered. Never pass a level that
 * doesn't come straight from the backend — the visual weight here must
 * never overstate what the backend actually concluded.
 */
export function ConfidenceBadge({ level, size = 'md', className }: { level: ConfidenceLevel | null | undefined; size?: 'sm' | 'md' | 'lg'; className?: string }) {
  const tone = confidenceTone(level)
  const sizeClasses = size === 'lg' ? 'px-3 py-1.5 text-sm' : size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-1 text-xs'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-(--radius-xs) font-bold uppercase tracking-wide',
        tone.bg,
        tone.fg,
        sizeClasses,
        className,
      )}
    >
      <span className={cn('inline-block size-1.5 rounded-full', tone.dot)} />
      {tone.label}
    </span>
  )
}
