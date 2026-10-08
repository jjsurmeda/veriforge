import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from '@tanstack/react-router'

import { ensureSession } from './lib/auth'
import { AppShell } from './components/AppShell'
import { AdminPage } from './features/admin/AdminPage'
import { ForgotPasswordPage } from './features/auth/pages/ForgotPasswordPage'
import { LoginPage } from './features/auth/pages/LoginPage'
import { OAuthCallbackPage } from './features/auth/pages/OAuthCallbackPage'
import { ResetPasswordPage } from './features/auth/pages/ResetPasswordPage'
import { SignupPage } from './features/auth/pages/SignupPage'
import { ChatIndexPage } from './features/chat/pages/ChatIndexPage'
import { ChatView } from './features/chat/pages/ChatView'
import { DecisionLayerPage } from './features/trace/pages/DecisionLayerPage'

const rootRoute = createRootRoute({ component: Outlet })

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
})
const signupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/signup',
  component: SignupPage,
})
const forgotPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/forgot-password',
  component: ForgotPasswordPage,
})
const resetPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/reset-password',
  validateSearch: (search: Record<string, unknown>) => ({
    token: typeof search.token === 'string' ? search.token : '',
  }),
  component: function ResetPassword() {
    const { token } = resetPasswordRoute.useSearch()
    return <ResetPasswordPage token={token} />
  },
})
const oauthCallbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/auth/callback',
  component: OAuthCallbackPage,
})

const appLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app',
  component: AppShell,
  beforeLoad: async () => {
    if (!(await ensureSession())) {
      throw redirect({ to: '/login' })
    }
  },
})

const indexRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/',
  component: ChatIndexPage,
})
const chatRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/chat/$chatId',
  component: function ChatRouteComponent() {
    const { chatId } = chatRoute.useParams()
    return <ChatView chatId={chatId} />
  },
})
const libraryRedirectRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/library',
  beforeLoad: () => {
    throw redirect({ to: '/' })
  },
})
const sourcesRedirectRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/sources',
  beforeLoad: () => {
    throw redirect({ to: '/' })
  },
})

const adminRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/admin',
  component: AdminPage,
})

// Lane E item 3: readable by the demo role, which `AdminPage` refuses at the
// role check. The page renders only the read-only decision statistics — every
// other section of /admin stays behind `me.data?.role !== 'admin'`.
const decisionLayerRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/decision-layer',
  component: DecisionLayerPage,
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  signupRoute,
  forgotPasswordRoute,
  resetPasswordRoute,
  oauthCallbackRoute,
  appLayoutRoute.addChildren([
    indexRoute,
    chatRoute,
    libraryRedirectRoute,
    sourcesRedirectRoute,
    adminRoute,
    decisionLayerRoute,
  ]),
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
