import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/common/Tabs'
import { ContributionChart } from './ContributionChart'
import type { DriverDecompositionResult } from '@/types/driver'
import { useClearanceAllowsInternal } from '@/hooks/useDrivers'
import { getSegmentContributions } from '@/api'
import { useQuery } from '@tanstack/react-query'

export function DriverDrilldown({ decomposition }: { decomposition: DriverDecompositionResult }) {
  const [dimension, setDimension] = useState<'product_category' | 'customer_state' | 'seller' | 'seller_state'>('product_category')
  const allowsInternal = useClearanceAllowsInternal()
  const { data: segments } = useQuery({
    queryKey: ['segments', dimension, allowsInternal],
    queryFn: () => getSegmentContributions(dimension, allowsInternal),
  })

  return (
    <div>
      <Tabs value={dimension} onValueChange={(v) => setDimension(v as typeof dimension)}>
        <TabsList>
          <TabsTrigger value="product_category">Category</TabsTrigger>
          <TabsTrigger value="customer_state">Customer state</TabsTrigger>
          <TabsTrigger value="seller_state">Seller state</TabsTrigger>
          <TabsTrigger value="seller">Seller</TabsTrigger>
        </TabsList>
        <TabsContent value={dimension} className="mt-3">
          {segments ? <ContributionChart segments={segments} total={decomposition.pvm.mixEffect + decomposition.pvm.volumeEffect} /> : null}
        </TabsContent>
      </Tabs>
    </div>
  )
}
