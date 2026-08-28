/** Parses the real `key=value` factor strings the Confidence Judge writes
 * into HypothesisResult.reasons (e.g. "score=0.000", "completeness=0.000",
 * "n_supports=0") — never invents a percentage the backend didn't compute. */
export function parseFactors(reasons: string[]): { key: string; value: string }[] {
  return reasons
    .filter((r) => r.includes('='))
    .map((r) => {
      const [key, value] = r.split('=')
      return { key: key.trim(), value: value.trim() }
    })
}

export function ConfidenceFactors({ reasons }: { reasons: string[] }) {
  const factors = parseFactors(reasons)
  const textual = reasons.filter((r) => !r.includes('='))

  if (!factors.length && !textual.length) {
    return <p className="text-[12px] text-(--color-ink-faint)">No factor breakdown recorded for this hypothesis.</p>
  }

  return (
    <div className="space-y-2">
      {factors.length ? (
        <div className="grid grid-cols-2 gap-2">
          {factors.map((f) => (
            <div key={f.key} className="rounded-(--radius-sm) bg-(--color-surface-2) px-2.5 py-1.5">
              <p className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">{f.key.replaceAll('_', ' ')}</p>
              <p className="font-mono text-[13px] font-semibold text-(--color-ink)">{f.value}</p>
            </div>
          ))}
        </div>
      ) : null}
      {textual.length ? (
        <ul className="space-y-0.5">
          {textual.map((t, i) => (
            <li key={i} className="text-[12px] text-(--color-ink-muted)">
              · {t}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
