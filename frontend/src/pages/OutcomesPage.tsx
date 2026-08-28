import { Badge } from '@/components/common/Badge'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { LoadingState } from '@/components/common/LoadingState'
import { FeedbackPanel } from '@/components/feedback/FeedbackPanel'
import { useDecisions } from '@/hooks/useDecisions'
import { useFeedbackCases, useFeedbackSummary, useRegressionComparison } from '@/hooks/useFeedback'
import { titleCase } from '@/lib/format'

export function OutcomesPage() {
  const { data: decisions, isLoading: loadingDecisions } = useDecisions()
  const { data: cases, isLoading: loadingCases } = useFeedbackCases()
  const { data: summary } = useFeedbackSummary()
  const { data: regression } = useRegressionComparison()

  return (
    <div className="mx-auto max-w-[1200px] space-y-5 px-6 py-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">Outcomes</p>
        <h1 className="text-xl font-bold text-(--color-ink)">Impact & feedback</h1>
      </div>

      <Card>
        <CardHeader title="Predicted vs. actual impact" subtitle="Monitoring targets from the real Step 7 recommendations" />
        <CardBody className="!p-0">
          {loadingDecisions || !decisions ? (
            <LoadingState label="Loading monitoring targets" />
          ) : (
            <table className="w-full text-left text-[12px]">
              <thead>
                <tr className="border-b border-(--color-border) text-[10px] uppercase tracking-wide text-(--color-ink-faint)">
                  <th className="px-4 py-2 font-medium">Action</th>
                  <th className="px-4 py-2 font-medium">Owner</th>
                  <th className="px-4 py-2 font-medium">Predicted</th>
                  <th className="px-4 py-2 font-medium">Actual</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {Object.values(decisions)
                  .map((d) => d.topRecommendation)
                  .filter((a): a is NonNullable<typeof a> => !!a)
                  .flatMap((a) => a.monitoringKpis.map((m) => ({ action: a, m })))
                  .map(({ action, m }) => (
                    <tr key={`${action.recommendationId}-${m.kpi}`} className="border-b border-(--color-border) last:border-0">
                      <td className="px-4 py-2 font-medium text-(--color-ink)">{action.possibleAction}</td>
                      <td className="px-4 py-2 text-(--color-ink-muted)">{action.owner}</td>
                      <td className="px-4 py-2 tabular text-(--color-ink)">
                        {m.direction} {m.kpi.replaceAll('_', ' ')} by ~{m.expectedEffect} over {m.window.replaceAll('_', ' ')}
                      </td>
                      <td className="px-4 py-2 text-(--color-ink-faint)">
                        <Badge tone="neutral">pending — window not yet elapsed</Badge>
                      </td>
                      <td className="px-4 py-2">
                        <Badge tone="warning">MONITORING</Badge>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </CardBody>
        <div className="border-t border-(--color-border) px-4 py-2.5 text-[11px] text-(--color-ink-faint)">
          This demo's scenario is historical (Oct → Nov 2017) — no forward-looking monitoring window has actually elapsed, so
          "actual" is honestly shown as pending rather than a fabricated number.
        </div>
      </Card>

      <Card>
        <CardHeader title="Regression test harness" subtitle="Step 9 — synthetic candidate vs. baseline, proving the eval harness catches regressions" />
        <CardBody>
          {regression ? (
            <div className="grid grid-cols-4 gap-3">
              {Object.entries(regression.baseline_metrics).map(([metric, baseline]) => (
                <div key={metric} className="rounded-(--radius-sm) bg-(--color-surface-2) p-2.5">
                  <p className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">{metric.replaceAll('_', ' ')}</p>
                  <p className="text-[13px] tabular">
                    <span className="font-semibold text-(--color-positive)">{baseline.toFixed(2)}</span>
                    <span className="mx-1 text-(--color-ink-faint)">→</span>
                    <span className="font-semibold text-(--color-negative)">{regression.candidate_metrics[metric].toFixed(2)}</span>
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <LoadingState />
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Feedback cases" subtitle={summary ? `${summary.total_feedback} submitted · ${summary.total_corrections} corrections · ${summary.total_regression_tests} regression tests` : undefined} />
        <CardBody className="space-y-2">
          {loadingCases || !cases ? (
            <LoadingState label="Loading feedback cases" />
          ) : (
            cases.map((c) => (
              <div key={c.key} className="rounded-(--radius-md) border border-(--color-border) p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] font-semibold text-(--color-ink-faint)">{c.feedbackId}</span>
                  <Badge tone={c.rating === 'CORRECT' ? 'positive' : c.rating === 'INCORRECT' ? 'negative' : 'warning'}>
                    {c.rating.replaceAll('_', ' ')}
                  </Badge>
                </div>
                <p className="mt-1 text-[13px] text-(--color-ink)">{c.summary}</p>
                {c.categories.length ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {c.categories.map((cat) => (
                      <Badge key={cat} tone="neutral">
                        {titleCase(cat)}
                      </Badge>
                    ))}
                  </div>
                ) : null}
                {c.regressionCaught && c.failureReasons.length ? (
                  <div className="mt-2 rounded-(--radius-sm) bg-(--color-negative-soft) px-2.5 py-1.5">
                    <p className="text-[11px] font-semibold text-(--color-negative)">Regression test caught this on re-run:</p>
                    <ul className="mt-0.5 space-y-0.5">
                      {c.failureReasons.map((r, i) => (
                        <li key={i} className="text-[11px] text-(--color-ink-muted)">
                          · {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Submit feedback" subtitle="On the current investigation (Revenue, Nov 2017)" />
        <CardBody>
          <FeedbackPanel />
        </CardBody>
      </Card>
    </div>
  )
}
