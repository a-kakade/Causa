import { FlaskConical, Radio } from 'lucide-react'
import { useAppState } from '@/state/AppStateContext'

/** Spec §52: the app's current data source must be clearly, persistently
 * identified — and that identification must be TRUE, not a hardcoded claim.
 * Reads the same `apiMode` the Header's Live/Demo toggle sets (@/api/mode.ts
 * is the actual dispatch) — this banner never asserts a mode independently
 * of the real wiring. */
export function DemoModeBanner() {
  const { apiMode } = useAppState()
  if (apiMode === 'demo') {
    return (
      <div className="flex items-center gap-2 border-b border-(--color-accent-border) bg-(--color-accent-soft) px-4 py-1.5 text-[11px] font-medium text-(--color-accent-strong)">
        <FlaskConical className="size-3" />
        DEMO MODE — real backend-computed output, Oct → Nov 2017 Olist scenario, served from static fixtures (no live API)
      </div>
    )
  }
  return (
    <div className="flex items-center gap-2 border-b border-(--color-border) bg-(--color-positive-soft) px-4 py-1.5 text-[11px] font-medium text-(--color-positive)">
      <Radio className="size-3" />
      LIVE API — every value on this page comes from a real HTTP call to the FastAPI backend (causa/api/), which calls
      the real Step 1-9 engines directly. No static fixtures are involved.
    </div>
  )
}
