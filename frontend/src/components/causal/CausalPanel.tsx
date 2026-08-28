import { ShieldAlert, ShieldCheck } from 'lucide-react'
import { EligibilityChecklist } from './Diagnostics'
import { MethodBadge, TierBadge } from './MethodBadge'
import { formatCurrency } from '@/lib/format'
import type { CausalResult } from '@/types/causal'

export function CausalPanel({ result }: { result: CausalResult }) {
  return (
    <div className="space-y-3 rounded-(--radius-md) border border-(--color-border) p-3.5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <p className="font-mono text-[11px] font-semibold text-(--color-ink-faint)">{result.hypothesisId}</p>
          <MethodBadge method={result.method} />
          <TierBadge tier={result.evidenceTier} />
        </div>
      </div>

      <div
        className={`flex items-center gap-2 rounded-(--radius-sm) px-3 py-2 text-[12px] font-bold uppercase tracking-wide ${
          result.causalClaimAllowed
            ? 'bg-(--color-positive-soft) text-(--color-positive)'
            : 'bg-(--color-negative-soft) text-(--color-negative)'
        }`}
      >
        {result.causalClaimAllowed ? <ShieldCheck className="size-4" /> : <ShieldAlert className="size-4" />}
        {result.causalClaimAllowed ? 'Causal claim supported' : 'Causal claim not established'}
      </div>

      {result.estimate ? (
        <div className="flex flex-wrap gap-4">
          {Object.entries(result.estimate).map(([k, v]) => (
            <div key={k}>
              <p className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">{k.replaceAll('_', ' ')}</p>
              <p className="text-[13px] font-semibold tabular text-(--color-ink)">
                {typeof v === 'number' && (k.includes('effect') || k.includes('value')) ? formatCurrency(v) : String(v)}
              </p>
            </div>
          ))}
        </div>
      ) : null}

      <EligibilityChecklist report={result.eligibilityReport} />

      {result.confounders.length ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Confounders identified</p>
          <p className="text-[12px] text-(--color-ink-muted)">{result.confounders.map((c) => c.replaceAll('_', ' ')).join(', ')}</p>
        </div>
      ) : null}

      {result.limitations.length ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Limitations</p>
          <ul className="list-disc space-y-0.5 pl-4">
            {result.limitations.map((l, i) => (
              <li key={i} className="text-[12px] text-(--color-ink-muted)">
                {l}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
