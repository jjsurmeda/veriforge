import { Outlet, useRouterState } from '@tanstack/react-router'

import { AppHeader } from './AppHeader'

export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const isChatSurface = pathname === '/' || pathname.startsWith('/chat/')

  return (
    <div className="theme-transition flex h-dvh min-h-0 flex-col bg-main text-fg">
      {/* One Tab stop jumps past the sidebar (F-10). Pages own their <main>,
          so the target is found at click time rather than by a shared id. */}
      <a
        href="#main"
        onClick={(event) => {
          const main = document.querySelector('main')
          if (!main) return
          event.preventDefault()
          main.tabIndex = -1
          main.focus()
        }}
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[100] focus:rounded-lg focus:border focus:border-border-strong focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
      >
        Skip to main content
      </a>
      {!isChatSurface && <AppHeader />}
      <div className="min-h-0 flex-1">
        <Outlet />
      </div>
    </div>
  )
}
