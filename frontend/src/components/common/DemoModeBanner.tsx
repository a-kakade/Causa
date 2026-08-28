import { FlaskConical } from 'lucide-react'

/** Spec §52: DEMO MODE must be clearly, persistently identified. Values
 * shown throughout the app are real backend-computed output (Oct->Nov 2017
 * Olist scenario) served from static fixtures — never hand-authored. */
export function DemoModeBanner() {
  return (
    <div className="flex items-center gap-2 border-b border-(--color-accent-border) bg-(--color-accent-soft) px-4 py-1.5 text-[11px] font-medium text-(--color-accent-strong)">
      <FlaskConical className="size-3" />
      DEMO MODE — real backend-computed output, Oct → Nov 2017 Olist scenario, served from static fixtures (no live API)
    </div>
  )
}
