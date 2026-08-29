import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { Drawer } from '@/components/common/Drawer'
import { LoadingState } from '@/components/common/LoadingState'
import { useAllLogs } from '@/hooks/useLogs'
import type { LogEntry } from '@/api'
import { formatDateTime } from '@/lib/format'

const PAGE_SIZE = 20
const AGENT_ROLES = ['ORCHESTRATOR', 'HYPOTHESIS', 'EVIDENCE', 'COUNTER_EVIDENCE', 'CAUSAL_SELECTOR', 'CONFIDENCE_JUDGE']

export function LogsPage() {
  const { data: logs, isLoading } = useAllLogs()
  const [search, setSearch] = useState('')
  const [agentRole, setAgentRole] = useState('')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<LogEntry | null>(null)

  const filtered = useMemo(() => {
    if (!logs) return []
    return logs.filter((l) => {
      if (agentRole && l.agentRole !== agentRole) return false
      if (search) {
        const q = search.toLowerCase()
        const hay = `${l.agentId} ${l.toolCall ?? ''} ${l.output} ${l.investigationId}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [logs, search, agentRole])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageItems = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 px-6 py-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">System</p>
        <h1 className="text-xl font-bold text-(--color-ink)">Audit logs</h1>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex flex-1 items-center gap-2 rounded-(--radius-sm) border border-(--color-border) bg-(--color-surface) px-2.5 py-1.5">
          <Search className="size-3.5 text-(--color-ink-faint)" />
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(0)
            }}
            placeholder="Search agent, tool, output, investigation ID…"
            className="w-full bg-transparent text-[12px] text-(--color-ink) placeholder:text-(--color-ink-faint) focus:outline-none"
          />
        </div>
        <select
          value={agentRole}
          onChange={(e) => {
            setAgentRole(e.target.value)
            setPage(0)
          }}
          className="rounded-(--radius-sm) border border-(--color-border) bg-(--color-surface) px-2.5 py-1.5 text-[12px] text-(--color-ink)"
        >
          <option value="">All agents</option>
          {AGENT_ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>

      <Card>
        <CardHeader title={`${filtered.length} events`} />
        <CardBody className="!p-0">
          {isLoading ? (
            <LoadingState label="Loading logs" />
          ) : (
            <table className="w-full text-left text-[12px]">
              <thead>
                <tr className="border-b border-(--color-border) text-[10px] uppercase tracking-wide text-(--color-ink-faint)">
                  <th className="px-4 py-2 font-medium">Timestamp</th>
                  <th className="px-4 py-2 font-medium">Component</th>
                  <th className="px-4 py-2 font-medium">Event</th>
                  <th className="px-4 py-2 font-medium">Duration</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((l) => (
                  <tr
                    key={l.id}
                    onClick={() => setSelected(l)}
                    className="cursor-pointer border-b border-(--color-border) transition-colors last:border-0 hover:bg-(--color-surface-2)"
                  >
                    <td className="px-4 py-2 font-mono text-(--color-ink-faint)">{formatDateTime(l.timestamp)}</td>
                    <td className="px-4 py-2 font-medium text-(--color-ink)">{l.agentId}</td>
                    <td className="px-4 py-2 font-mono text-(--color-ink-muted)">{l.toolCall ?? '(no tool call)'}</td>
                    <td className="px-4 py-2 tabular text-(--color-ink-muted)">{l.latencyMs ? `${l.latencyMs.toFixed(0)}ms` : '—'}</td>
                    <td className="px-4 py-2 text-(--color-ink-muted)">{l.securityDecision ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
        <div className="flex items-center justify-between border-t border-(--color-border) px-4 py-2.5 text-[12px] text-(--color-ink-muted)">
          <span>
            Page {page + 1} of {pageCount}
          </span>
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="rounded-(--radius-sm) border border-(--color-border-strong) px-2.5 py-1 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              type="button"
              disabled={page >= pageCount - 1}
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              className="rounded-(--radius-sm) border border-(--color-border-strong) px-2.5 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </Card>

      <Drawer open={!!selected} onOpenChange={(o) => !o && setSelected(null)} title={selected?.agentId ?? ''} subtitle={selected?.toolCall ?? undefined}>
        {selected ? (
          <div className="space-y-3 text-[12px]">
            <Field label="Event ID" value={selected.id} />
            <Field label="Investigation ID" value={selected.investigationId} />
            <Field label="Requester role" value={selected.requesterRole} />
            <Field label="Agent" value={`${selected.agentId} (${selected.agentRole})`} />
            <Field label="Tool" value={selected.toolCall ?? '—'} />
            <Field label="Evidence IDs touched" value={selected.toolResultIds.length ? selected.toolResultIds.join(', ') : '—'} />
            <Field label="Latency" value={selected.latencyMs ? `${selected.latencyMs.toFixed(2)}ms` : '—'} />
            <Field label="Token usage" value={String(selected.tokenUsage)} />
            <Field label="Security decision" value={selected.securityDecision ?? '—'} />
            <Field label="Output" value={selected.output} />
            <Field label="Timestamp" value={formatDateTime(selected.timestamp)} />
          </div>
        ) : null}
      </Drawer>
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">{label}</p>
      <p className="break-words font-mono text-[12px] text-(--color-ink)">{value}</p>
    </div>
  )
}
