import { Outlet } from 'react-router-dom'
import { DemoModeBanner } from '@/components/common/DemoModeBanner'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

export function AppShell() {
  return (
    <div className="flex h-screen flex-col bg-(--color-paper)">
      <DemoModeBanner />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header />
          <main className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  )
}
