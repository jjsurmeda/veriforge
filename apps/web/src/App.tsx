import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'

import './lib/api'
import { queryClient } from './lib/queryClient'
import { router } from './router'
import { ThemeProvider } from './components/ThemeToggle'
import { TooltipProvider } from './components/ui/primitives'

function App() {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={300}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </TooltipProvider>
    </ThemeProvider>
  )
}

export default App
