import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import './index.css'
import { AppStateProvider } from '@/state/AppStateContext'
import { TooltipProvider } from '@/components/common/Tooltip'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppStateProvider>
        <TooltipProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </TooltipProvider>
      </AppStateProvider>
    </QueryClientProvider>
  </StrictMode>,
)
