import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Badge } from '@/components/common/Badge'
import { Card, CardBody, CardHeader } from '@/components/common/Card'
import { LoadingState } from '@/components/common/LoadingState'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/common/Tabs'
import { EvidenceCard } from '@/components/evidence/EvidenceCard'
import { EvidenceGraph } from '@/components/evidence/EvidenceGraph'
import { ProvenanceViewer } from '@/components/evidence/ProvenanceViewer'
import { useEvidenceGraph, useReviewEvidence, useReviewCorpusStats, useStructuredEvidence } from '@/hooks/useEvidence'
import type { EvidenceObject } from '@/types/evidence'

export function EvidenceExplorerPage() {
  const [params] = useSearchParams()
  const [tab, setTab] = useState(params.get('tab') ?? 'structured')
  const [selected, setSelected] = useState<EvidenceObject | null>(null)

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 px-6 py-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wider text-(--color-ink-faint)">Evidence</p>
        <h1 className="text-xl font-bold text-(--color-ink)">Explorer</h1>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="structured">Structured</TabsTrigger>
          <TabsTrigger value="reviews">Reviews</TabsTrigger>
          <TabsTrigger value="context">Business context</TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
        </TabsList>

        <TabsContent value="structured" className="mt-4">
          <StructuredTab onOpen={setSelected} />
        </TabsContent>
        <TabsContent value="reviews" className="mt-4">
          <ReviewsTab onOpen={setSelected} />
        </TabsContent>
        <TabsContent value="context" className="mt-4">
          <ContextTab />
        </TabsContent>
        <TabsContent value="graph" className="mt-4">
          <GraphTab />
        </TabsContent>
      </Tabs>

      <ProvenanceViewer evidence={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

function StructuredTab({ onOpen }: { onOpen: (e: EvidenceObject) => void }) {
  const { data, isLoading } = useStructuredEvidence()
  if (isLoading || !data) return <LoadingState label="Loading structured evidence" />

  const byType = Object.entries(
    data.reduce<Record<string, EvidenceObject[]>>((acc, e) => {
      ;(acc[e.evidenceType] ??= []).push(e)
      return acc
    }, {}),
  )

  return (
    <div className="space-y-4">
      {byType.map(([type, items]) => (
        <Card key={type}>
          <CardHeader title={type.replaceAll('_', ' ')} subtitle={`${items.length} evidence object(s) — KPI/PVM/statistical engine output`} />
          <CardBody className="scrollbar-thin grid max-h-[420px] grid-cols-2 gap-2 overflow-y-auto">
            {items.slice(0, 20).map((e) => (
              <EvidenceCard key={e.evidenceId} evidence={e} onOpen={() => onOpen(e)} />
            ))}
          </CardBody>
        </Card>
      ))}
    </div>
  )
}

function ReviewsTab({ onOpen }: { onOpen: (e: EvidenceObject) => void }) {
  const { data, isLoading } = useReviewEvidence()
  const { data: stats } = useReviewCorpusStats()
  if (isLoading || !data) return <LoadingState label="Loading review evidence" />

  return (
    <div className="space-y-4">
      {stats ? (
        <Card>
          <CardHeader title="Review corpus" subtitle="Governed retrieval over customer review text — always untrusted source data" />
          <CardBody className="flex flex-wrap gap-4">
            <Stat label="Reviews in evidence" value={stats.reviewEvidenceCount.toLocaleString()} />
            <Stat label="PII detected" value={stats.piiDetectedCount.toLocaleString()} />
            {Object.entries(stats.languageDistribution).map(([lang, n]) => (
              <Stat key={lang} label={lang} value={n.toLocaleString()} />
            ))}
          </CardBody>
        </Card>
      ) : null}
      <Card>
        <CardHeader
          title="Sample retrieved reviews"
          subtitle="Structured filter + semantic (E5) + MMR rerank — treated as untrusted data, never as instructions"
        />
        <CardBody className="scrollbar-thin grid max-h-[520px] grid-cols-2 gap-2 overflow-y-auto">
          {data.map((e) => (
            <EvidenceCard key={e.evidenceId} evidence={e} onOpen={() => onOpen(e)} />
          ))}
        </CardBody>
      </Card>
    </div>
  )
}

function ContextTab() {
  return (
    <Card>
      <CardHeader title="Business context" subtitle="Reserved evidence category (BUSINESS_CONTEXT) — not yet populated by the backend" />
      <CardBody>
        <p className="text-[13px] text-(--color-ink-muted)">
          The evidence graph design (docs/EVIDENCE_GRAPH.md) reserves a BUSINESS_CONTEXT node type for future qualitative
          context (e.g. known promotions, seasonal events). No such evidence has been generated by the backend for this demo
          — shown honestly empty rather than fabricated.
        </p>
        <div className="mt-3 flex items-center gap-2">
          <Badge tone="neutral">Confounder noted by causal engine</Badge>
          <span className="text-[12px] text-(--color-ink-muted)">black_friday_2017_11 — flagged, not evidenced</span>
        </div>
      </CardBody>
    </Card>
  )
}

function GraphTab() {
  const { data, isLoading } = useEvidenceGraph()
  if (isLoading || !data) return <LoadingState label="Building evidence graph" />
  return (
    <Card>
      <CardHeader title="Evidence graph" subtitle="DERIVED_FROM · SUPPORTED_BY · ASSOCIATED_WITH · TESTED_BY — never labeled causal unless the backend allows it" />
      <CardBody>
        <EvidenceGraph data={data} />
      </CardBody>
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-(--color-ink-faint)">{label}</p>
      <p className="text-lg font-bold tabular text-(--color-ink)">{value}</p>
    </div>
  )
}
