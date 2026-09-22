import { useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'

import { setAccessToken } from '../../../lib/auth'

export function OAuthCallbackPage() {
  const navigate = useNavigate()

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    const token = params.get('access_token')
    if (token) {
      setAccessToken(token)
      void navigate({ to: '/', replace: true })
    } else {
      void navigate({ to: '/login', replace: true })
    }
  }, [navigate])

  return (
    <main className="flex min-h-screen items-center justify-center bg-ink text-paper">
      <p className="text-sm text-paper/60">Signing you in…</p>
    </main>
  )
}
