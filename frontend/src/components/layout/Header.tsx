import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Bell, CheckCircle2, ChevronDown, HelpCircle, Loader2, Search, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { KPI_REGISTRY } from '@/api'
import { Modal } from '@/components/common/Modal'
import { StatusDot } from '@/components/common/StatusDot'
import { useAskQuestion } from '@/hooks/useInvestigation'
import { AVAILABLE_PERIODS, useAppState } from '@/state/AppStateContext'
import type { RequesterRole } from '@/types/common'
import { formatMonthLabel } from '@/lib/format'

const ROLES: { value: RequesterRole; label: string; clearance: string }[] = [
  { value: 'EXECUTIVE', label: 'Executive', clearance: 'PUBLIC_ANALYTICAL' },
  { value: 'ANALYST', label: 'Analyst', clearance: 'INTERNAL' },
  { value: 'INTERNAL', label: 'Internal (audit)', clearance: 'RESTRICTED' },
]

// Static pages the search bar can jump to, alongside the governed KPI
// catalog -- everything a person could plausibly type into this box.
const PAGES = [
  { label: 'Overview', path: '/overview' },
  { label: 'Investigate history', path: '/investigate' },
  { label: 'Evidence explorer', path: '/evidence' },
  { label: 'Decisions', path: '/decisions' },
  { label: 'Outcomes', path: '/outcomes' },
  { label: 'Security', path: '/security' },
  { label: 'Telemetry', path: '/telemetry' },
  { label: 'Audit logs', path: '/logs' },
]

export function Header() {
  const { requesterRole, setRequesterRole, startPeriod, endPeriod, setPeriodRange } = useAppState()
  const role = ROLES.find((r) => r.value === requesterRole)!

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-(--color-border) bg-(--color-surface) px-4">
      <div className="flex items-center gap-4 text-[13px]">
        <div>
          <span className="text-(--color-ink-faint)">Workspace</span>{' '}
          <span className="font-medium text-(--color-ink)">Revenue Intelligence</span>
        </div>
        <div className="h-4 w-px bg-(--color-border)" />
        <PeriodSelector start={startPeriod} end={endPeriod} onChange={setPeriodRange} />
        <div className="h-4 w-px bg-(--color-border)" />
        <div className="flex items-center gap-1.5">
          <StatusDot tone="positive" />
          <span className="text-(--color-ink-muted)">Fixtures current</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <ApiModeToggle />
        <div className="h-4 w-px bg-(--color-border)" />
        <AskQuestionButton />
        <HeaderSearch />
        <button
          type="button"
          className="rounded-(--radius-sm) p-1.5 text-(--color-ink-faint) transition-colors hover:bg-(--color-surface-2) hover:text-(--color-ink)"
          aria-label="Notifications"
        >
          <Bell className="size-4" />
        </button>
        <div className="h-4 w-px bg-(--color-border)" />

        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button type="button" className="flex items-center gap-2 rounded-(--radius-sm) py-1 pl-1 pr-2 hover:bg-(--color-surface-2)">
              <div className="flex size-6 items-center justify-center rounded-full bg-(--color-accent-soft) text-[11px] font-bold text-(--color-accent-strong)">
                {role.label[0]}
              </div>
              <div className="text-left leading-tight">
                <div className="text-[12px] font-medium text-(--color-ink)">{role.label}</div>
                <div className="text-[10px] text-(--color-ink-faint)">{role.clearance}</div>
              </div>
              <ChevronDown className="size-3 text-(--color-ink-faint)" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={8}
              className="z-50 w-64 rounded-(--radius-md) border border-(--color-border) bg-(--color-surface) p-1 shadow-(--shadow-md)"
            >
              <p className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">
                Switch requester role (RBAC demo)
              </p>
              {ROLES.map((r) => (
                <DropdownMenu.Item
                  key={r.value}
                  onSelect={() => setRequesterRole(r.value)}
                  className="flex cursor-pointer items-center justify-between rounded-(--radius-sm) px-2.5 py-1.5 text-[13px] text-(--color-ink) outline-none data-[highlighted]:bg-(--color-surface-2)"
                >
                  <span>{r.label}</span>
                  <span className="text-[10px] font-mono text-(--color-ink-faint)">{r.clearance}</span>
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </header>
  )
}

/** Live/Demo switch -- Live routes every call through @/api/productionApi
 * (the real FastAPI backend); Demo routes through @/api/demoAdapter (offline,
 * reads the static fixture copy of a real validated run, no backend needed).
 * See @/api/mode.ts for the dispatch this flips. */
function ApiModeToggle() {
  const { apiMode, setApiMode } = useAppState()
  const isDemo = apiMode === 'demo'

  return (
    <button
      type="button"
      onClick={() => setApiMode(isDemo ? 'live' : 'demo')}
      title={isDemo ? 'Switch to Live (real backend)' : 'Switch to Demo (offline fixtures, no backend needed)'}
      className="flex items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border) px-2.5 py-1 text-[12px] font-medium transition-colors hover:bg-(--color-surface-2)"
    >
      <StatusDot tone={isDemo ? 'warning' : 'positive'} />
      <span className={isDemo ? 'text-(--color-warning)' : 'text-(--color-ink-muted)'}>
        {isDemo ? 'Demo mode' : 'Live'}
      </span>
    </button>
  )
}

function PeriodSelector({ start, end, onChange }: { start: string; end: string; onChange: (start: string, end: string) => void }) {
  const label = start === end
    ? formatMonthLabel(end)
    : `${formatMonthLabel(start)} – ${formatMonthLabel(end)}`

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className="flex items-center gap-1 rounded-(--radius-sm) px-1 py-0.5 hover:bg-(--color-surface-2)">
          <span className="text-(--color-ink-faint)">Period</span>
          <span className="font-medium text-(--color-ink)">{label}</span>
          <ChevronDown className="size-3 text-(--color-ink-faint)" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={8}
          className="z-50 flex w-[21rem] gap-2 rounded-(--radius-md) border border-(--color-border) bg-(--color-surface) p-2 shadow-(--shadow-md)"
        >
          <MonthColumn label="From" selected={start} options={AVAILABLE_PERIODS.filter((p) => p <= end)} onSelect={(p) => onChange(p, end)} />
          <MonthColumn label="To" selected={end} options={AVAILABLE_PERIODS.filter((p) => p >= start)} onSelect={(p) => onChange(start, p)} />
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

function MonthColumn({ label, selected, options, onSelect }: {
  label: string; selected: string; options: string[]; onSelect: (p: string) => void
}) {
  return (
    <div className="max-h-72 flex-1 overflow-y-auto">
      <p className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-(--color-ink-faint)">{label}</p>
      {options.map((p) => (
        <DropdownMenu.Item
          key={p}
          onSelect={(e) => {
            e.preventDefault()
            onSelect(p)
          }}
          className="flex cursor-pointer items-center justify-between rounded-(--radius-sm) px-2.5 py-1.5 text-[13px] text-(--color-ink) outline-none data-[highlighted]:bg-(--color-surface-2)"
        >
          <span>{formatMonthLabel(p)}</span>
          {p === selected ? <CheckCircle2 className="size-3.5 text-(--color-accent)" /> : null}
        </DropdownMenu.Item>
      ))}
    </div>
  )
}

function HeaderSearch() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClickOutside)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    const kpiMatches = KPI_REGISTRY
      .filter((k) => !q || k.name.toLowerCase().includes(q) || k.kpiId.toLowerCase().includes(q))
      .map((k) => ({ kind: 'kpi' as const, label: k.name, path: `/investigate/${k.kpiId}` }))
    const pageMatches = PAGES.filter((p) => !q || p.label.toLowerCase().includes(q)).map((p) => ({
      kind: 'page' as const, label: p.label, path: p.path,
    }))
    return [...kpiMatches, ...pageMatches].slice(0, 8)
  }, [query])

  function go(path: string) {
    navigate(path)
    setOpen(false)
    setQuery('')
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="rounded-(--radius-sm) p-1.5 text-(--color-ink-faint) transition-colors hover:bg-(--color-surface-2) hover:text-(--color-ink)"
        aria-label="Search"
      >
        <Search className="size-4" />
      </button>
      {open ? (
        <div className="absolute right-0 top-9 z-50 w-72 rounded-(--radius-md) border border-(--color-border) bg-(--color-surface) p-2 shadow-(--shadow-md)">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && results.length > 0) go(results[0].path)
            }}
            placeholder="Search KPIs and pages…"
            className="w-full rounded-(--radius-sm) border border-(--color-border) bg-(--color-surface-2) px-2.5 py-1.5 text-[12px] text-(--color-ink) placeholder:text-(--color-ink-faint) focus:outline-none"
          />
          <div className="mt-1.5 max-h-64 overflow-y-auto">
            {results.length === 0 ? (
              <p className="px-2 py-2 text-[12px] text-(--color-ink-faint)">No matches.</p>
            ) : (
              results.map((r) => (
                <button
                  key={`${r.kind}-${r.path}`}
                  type="button"
                  onClick={() => go(r.path)}
                  className="flex w-full items-center justify-between rounded-(--radius-sm) px-2.5 py-1.5 text-left text-[13px] text-(--color-ink) hover:bg-(--color-surface-2)"
                >
                  <span>{r.label}</span>
                  <span className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">{r.kind}</span>
                </button>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function AskQuestionButton() {
  const { askQuestionOpen, askQuestionPrefill, openAskQuestion, closeAskQuestion } = useAppState()
  const [question, setQuestion] = useState('')
  const navigate = useNavigate()
  const { mutate, data, isPending, error, reset } = useAskQuestion()

  // Seed the textarea whenever the modal opens with a prefill (e.g. from
  // AbstentionState's "Ask a clarifying question" button) or is reopened
  // fresh from the header's own Sparkles button (prefill === '').
  useEffect(() => {
    if (askQuestionOpen) setQuestion(askQuestionPrefill)
  }, [askQuestionOpen, askQuestionPrefill])

  function handleOpenChange(next: boolean) {
    if (next) {
      openAskQuestion()
    } else {
      closeAskQuestion()
      setQuestion('')
      reset()
    }
  }

  function handleSubmit() {
    if (!question.trim() || isPending) return
    mutate(question.trim())
  }

  return (
    <>
      <button
        type="button"
        onClick={() => openAskQuestion()}
        className="flex items-center gap-1.5 rounded-(--radius-sm) border border-(--color-border) px-2.5 py-1 text-[12px] font-medium text-(--color-ink-muted) transition-colors hover:bg-(--color-surface-2) hover:text-(--color-ink)"
      >
        <Sparkles className="size-3.5" />
        Ask a question
      </button>
      <Modal open={askQuestionOpen} onOpenChange={handleOpenChange} title="Ask your own question">
        <div className="space-y-3">
          <p className="text-[12px] text-(--color-ink-faint)">
            Type a question in plain English. It's resolved to a governed KPI and month, then a real
            investigation runs against that data — nothing is fabricated.
          </p>
          <textarea
            autoFocus
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
            }}
            rows={3}
            placeholder="e.g. Why did on-time delivery drop in September 2017?"
            className="w-full resize-none rounded-(--radius-sm) border border-(--color-border) bg-(--color-surface-2) px-2.5 py-2 text-[13px] text-(--color-ink) placeholder:text-(--color-ink-faint) focus:outline-none"
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!question.trim() || isPending}
            className="flex w-full items-center justify-center gap-1.5 rounded-(--radius-sm) bg-(--color-accent) px-3 py-1.5 text-[13px] font-medium text-(--color-ink-inverse) transition-opacity disabled:opacity-50"
          >
            {isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
            {isPending ? 'Investigating…' : 'Ask'}
          </button>

          {error ? (
            <p className="rounded-(--radius-sm) bg-(--color-negative-soft,var(--color-surface-2)) px-2.5 py-2 text-[12px] text-(--color-negative)">
              {(error as Error).message}
            </p>
          ) : null}

          {data ? (
            <div className="space-y-2 rounded-(--radius-sm) border border-(--color-border) bg-(--color-surface-2) px-2.5 py-2.5">
              <div className="flex items-center justify-between text-[12px]">
                <span className="text-(--color-ink-faint)">Resolved to</span>
                <span className="font-medium text-(--color-ink)">
                  {data.kpiId} · {formatMonthLabel(data.periodCurrent)}
                </span>
              </div>
              <div className="flex items-center justify-between text-[12px]">
                <span className="text-(--color-ink-faint)">Status</span>
                <span className="flex items-center gap-1 font-medium text-(--color-ink)">
                  {data.state.status === 'ABSTAINED' ? <HelpCircle className="size-3.5" /> : <CheckCircle2 className="size-3.5" />}
                  {data.state.status.replaceAll('_', ' ')}
                </span>
              </div>
              <p className="text-[10px] text-(--color-ink-faint)">
                matched via {data.resolver === 'openai' ? 'OpenAI' : 'keyword matching'}
              </p>
              <button
                type="button"
                onClick={() => {
                  navigate(`/investigate/${data.kpiId}`)
                  handleOpenChange(false)
                }}
                className="text-[12px] font-medium text-(--color-accent)"
              >
                Open full investigation →
              </button>
            </div>
          ) : null}
        </div>
      </Modal>
    </>
  )
}
