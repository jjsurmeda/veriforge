import { LoaderCircle } from 'lucide-react'
import { useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'

import { setAccessToken } from '../../../lib/auth'
import { AuthShell } from '../components/AuthShell'

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
    <AuthShell title="Signing you in" description="Finishing the secure handoff to Veriforge.">
      <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-muted px-3 py-3 text-sm text-muted-foreground">
        <LoaderCircle size={18} className="animate-spin text-accent" aria-hidden="true" />
        One moment…
      </div>
    </AuthShell>
  )
}
