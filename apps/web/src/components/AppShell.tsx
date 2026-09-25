import { Outlet, useRouterState } from '@tanstack/react-router'

import { AppHeader } from './AppHeader'

export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const isChatSurface = pathname === '/' || pathname.startsWith('/chat/')

  return (
    <div className="theme-transition flex h-dvh min-h-0 flex-col bg-background text-foreground">
      {!isChatSurface && <AppHeader />}
      <div className="min-h-0 flex-1">
        <Outlet />
      </div>
    </div>
  )
}
