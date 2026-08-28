import { Lock, Unlock } from 'lucide-react'
import { useState } from 'react'
import { RBAC_CLEARANCE_FOR_ROLE, runRbacDemo } from '@/api/demoAdapter/security'
import { Badge } from '@/components/common/Badge'
import type { RequesterRole, SecurityClassification } from '@/types/common'

const KPI_ACCESS: { label: string; classification: SecurityClassification }[] = [
  { label: 'Revenue', classification: 'PUBLIC_ANALYTICAL' },
  { label: 'Region / customer state', classification: 'PUBLIC_ANALYTICAL' },
  { label: 'Seller-level revenue', classification: 'INTERNAL' },
  { label: 'Seller state', classification: 'INTERNAL' },
  { label: 'Customer PII (raw)', classification: 'RESTRICTED' },
]

const ROLES: RequesterRole[] = ['EXECUTIVE', 'ANALYST', 'INTERNAL']

export function RBACPanel({ role }: { role: RequesterRole }) {
  const [tryRole, setTryRole] = useState(role)
  const clearance = RBAC_CLEARANCE_FOR_ROLE[tryRole]

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">Try as role</p>
        <div className="mt-1 flex gap-1.5">
          {ROLES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setTryRole(r)}
              className={`rounded-(--radius-sm) border px-2.5 py-1 text-[12px] font-medium transition-colors ${
                tryRole === r ? 'border-(--color-accent) bg-(--color-accent-soft) text-(--color-accent-strong)' : 'border-(--color-border-strong) text-(--color-ink-muted)'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
        <p className="mt-1 text-[11px] text-(--color-ink-faint)">
          Clearance: <span className="font-mono font-semibold">{clearance}</span> (from src/tools/policy.py::RBAC_CLEARANCE_FOR_ROLE)
        </p>
      </div>

      <div className="space-y-1">
        {KPI_ACCESS.map((item) => {
          const result = runRbacDemo(tryRole, item.classification)
          const allowed = result.decision === 'ALLOWED'
          return (
            <div key={item.label} className="flex items-center justify-between rounded-(--radius-sm) border border-(--color-border) px-3 py-2">
              <span className="text-[13px] font-medium text-(--color-ink)">{item.label}</span>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-(--color-ink-faint)">{item.classification}</span>
                {allowed ? (
                  <Badge tone="positive" icon={<Unlock className="size-3" />}>
                    Allowed
                  </Badge>
                ) : (
                  <Badge tone="negative" icon={<Lock className="size-3" />}>
                    Restricted
                  </Badge>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <p className="text-[11px] text-(--color-ink-faint)">
        Restricted data is filtered before it ever reaches an LLM's context (src/evidence/access_control.py) — not merely
        hidden in this UI.
      </p>
    </div>
  )
}
