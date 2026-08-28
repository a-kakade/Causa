import { useState } from 'react'
import { Badge } from '@/components/common/Badge'
import type { FeedbackCategory } from '@/types/feedback'

const CATEGORIES: FeedbackCategory[] = ['DRIVER', 'EVIDENCE', 'CONFIDENCE', 'RECOMMENDATION', 'NARRATIVE']

export function FeedbackPanel() {
  const [rating, setRating] = useState<'CORRECT' | 'PARTIALLY_CORRECT' | 'INCORRECT' | null>(null)
  const [categories, setCategories] = useState<Set<FeedbackCategory>>(new Set())
  const [comment, setComment] = useState('')
  const [submitted, setSubmitted] = useState(false)

  function toggleCategory(c: FeedbackCategory) {
    setCategories((prev) => {
      const next = new Set(prev)
      if (next.has(c)) next.delete(c)
      else next.add(c)
      return next
    })
  }

  if (submitted) {
    return (
      <div className="rounded-(--radius-md) border border-(--color-positive-soft) bg-(--color-positive-soft) px-3 py-2.5 text-[12px] font-medium text-(--color-positive)">
        Feedback recorded — thanks. This demo doesn't persist submissions to a backend (none exists to receive them);
        production feedback would flow into the real Step 9 feedback store (src/feedback/store.py).
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-[12px] font-semibold text-(--color-ink)">Was this useful?</p>
      <div className="flex gap-2">
        {(['CORRECT', 'PARTIALLY_CORRECT', 'INCORRECT'] as const).map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setRating(r)}
            className={`rounded-(--radius-sm) border px-3 py-1.5 text-[12px] font-medium transition-colors ${
              rating === r ? 'border-(--color-accent) bg-(--color-accent-soft) text-(--color-accent-strong)' : 'border-(--color-border-strong) text-(--color-ink-muted) hover:bg-(--color-surface-2)'
            }`}
          >
            {r.replaceAll('_', ' ')}
          </button>
        ))}
      </div>

      {rating && rating !== 'CORRECT' ? (
        <div>
          <p className="text-[12px] font-semibold text-(--color-ink)">What was wrong?</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {CATEGORIES.map((c) => (
              <label key={c} className="flex cursor-pointer items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border) px-2.5 py-1 text-[12px]">
                <input type="checkbox" checked={categories.has(c)} onChange={() => toggleCategory(c)} className="accent-(--color-accent)" />
                {c}
              </label>
            ))}
          </div>
        </div>
      ) : null}

      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Optional comment"
        rows={2}
        className="w-full rounded-(--radius-sm) border border-(--color-border) bg-(--color-surface) px-2.5 py-2 text-[12px] text-(--color-ink) placeholder:text-(--color-ink-faint) focus:border-(--color-accent) focus:outline-none"
      />

      <button
        type="button"
        disabled={!rating}
        onClick={() => setSubmitted(true)}
        className="rounded-(--radius-sm) bg-(--color-accent) px-3.5 py-1.5 text-[12px] font-semibold text-(--color-ink-inverse) transition-colors hover:bg-(--color-accent-strong) disabled:cursor-not-allowed disabled:opacity-40"
      >
        Submit feedback
      </button>
      {categories.size ? <FeedbackPreview categories={[...categories]} /> : null}
    </div>
  )
}

function FeedbackPreview({ categories }: { categories: FeedbackCategory[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {categories.map((c) => (
        <Badge key={c} tone="warning">
          {c}
        </Badge>
      ))}
    </div>
  )
}
