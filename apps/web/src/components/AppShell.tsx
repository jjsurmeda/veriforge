import { Outlet } from '@tanstack/react-router'

import { AppHeader } from './AppHeader'

export function AppShell() {
  return (
    <div className="theme-transition flex h-dvh min-h-0 flex-col bg-background text-foreground">
      <AppHeader />
      <div className="min-h-0 flex-1">
        <Outlet />
      </div>
    </div>
  )
}
