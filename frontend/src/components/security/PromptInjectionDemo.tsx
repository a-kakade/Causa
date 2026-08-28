import { ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { runPromptInjectionDemo } from '@/api/demoAdapter/security'
import { Badge } from '@/components/common/Badge'
import { LoadingState } from '@/components/common/LoadingState'
import { usePromptInjectionFixtures } from '@/hooks/useSecurity'
import type { PromptInjectionDemoResult } from '@/types/security'

export function PromptInjectionDemo() {
  const { data: fixtures, isLoading } = usePromptInjectionFixtures()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [result, setResult] = useState<PromptInjectionDemoResult | null>(null)

  if (isLoading || !fixtures) return <LoadingState label="Loading fixtures" />

  function run(fixtureId: string) {
    const fixture = fixtures!.find((f) => f.fixtureId === fixtureId)
    if (!fixture) return
    setSelectedId(fixtureId)
    setResult(runPromptInjectionDemo(fixture))
  }

  return (
    <div className="space-y-3">
      <p className="text-[12px] text-(--color-ink-muted)">
        Real fixture strings from data/evidence/security_fixtures/prompt_injection_fixtures.json — synthetic test text only,
        never merged into the real review corpus.
      </p>
      <div className="space-y-1.5">
        {fixtures.map((f) => (
          <button
            key={f.fixtureId}
            type="button"
            onClick={() => run(f.fixtureId)}
            className={`block w-full rounded-(--radius-sm) border px-3 py-2 text-left text-[12px] transition-colors ${
              selectedId === f.fixtureId ? 'border-(--color-accent) bg-(--color-accent-soft)' : 'border-(--color-border) hover:bg-(--color-surface-2)'
            }`}
          >
            <span className="font-mono text-[10px] text-(--color-ink-faint)">{f.fixtureId}</span>
            <p className="mt-0.5 italic text-(--color-ink)">"{f.text}"</p>
          </button>
        ))}
      </div>

      {result ? (
        <div className="rounded-(--radius-md) border border-(--color-negative-soft) bg-(--color-negative-soft) p-3.5">
          <div className="flex items-center gap-2">
            <ShieldAlert className="size-4 text-(--color-negative)" />
            <p className="text-[12px] font-bold uppercase tracking-wide text-(--color-negative)">Blocked</p>
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
            <Field label="Source" value={result.source} />
            <Field label="Classification" value={result.classification} />
            <Field label="Detected" value={result.detected.join(', ')} />
            <Field label="Action" value={result.action} tone="negative" />
            <Field label="Tool execution" value={result.toolExecution} tone="positive" />
            <Field label="Data disclosure" value={result.dataDisclosure} tone="positive" />
          </dl>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Badge tone="neutral">Select a fixture above to run the classifier</Badge>
        </div>
      )}
    </div>
  )
}

function Field({ label, value, tone }: { label: string; value: string; tone?: 'positive' | 'negative' }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">{label}</dt>
      <dd className={`font-mono font-semibold ${tone === 'positive' ? 'text-(--color-positive)' : tone === 'negative' ? 'text-(--color-negative)' : 'text-(--color-ink)'}`}>
        {value}
      </dd>
    </div>
  )
}
