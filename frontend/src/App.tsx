import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { DecisionsPage } from '@/pages/DecisionsPage'
import { EvidenceExplorerPage } from '@/pages/EvidenceExplorerPage'
import { InvestigateHistoryPage } from '@/pages/InvestigateHistoryPage'
import { InvestigatePage } from '@/pages/InvestigatePage'
import { LogsPage } from '@/pages/LogsPage'
import { OutcomesPage } from '@/pages/OutcomesPage'
import { OverviewPage } from '@/pages/OverviewPage'
import { SecurityPage } from '@/pages/SecurityPage'
import { TelemetryPage } from '@/pages/TelemetryPage'

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/overview" replace />} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="investigate" element={<InvestigateHistoryPage />} />
        <Route path="investigate/:kpiId" element={<InvestigatePage />} />
        <Route path="evidence" element={<EvidenceExplorerPage />} />
        <Route path="decisions" element={<DecisionsPage />} />
        <Route path="outcomes" element={<OutcomesPage />} />
        <Route path="security" element={<SecurityPage />} />
        <Route path="telemetry" element={<TelemetryPage />} />
        <Route path="logs" element={<LogsPage />} />
        <Route path="*" element={<Navigate to="/overview" replace />} />
      </Route>
    </Routes>
  )
}
