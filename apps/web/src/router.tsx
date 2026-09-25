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
import { LibraryPage } from './features/library/pages/LibraryPage'

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
const libraryRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/library',
  component: LibraryPage,
})
const sourcesRedirectRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/sources',
  beforeLoad: () => {
    throw redirect({ to: '/library' })
  },
})

const adminRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: '/admin',
  component: AdminPage,
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
    libraryRoute,
    sourcesRedirectRoute,
    adminRoute,
  ]),
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
