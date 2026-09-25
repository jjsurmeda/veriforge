import type { ReactNode } from 'react'
import { ShieldCheck, Sparkles } from 'lucide-react'

import { ThemeToggle } from '../../../components/ThemeToggle'

interface AuthShellProps {
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
}

export function AuthShell({ title, description, children, footer }: AuthShellProps) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-main px-4 py-10 text-fg sm:px-6">
      <div className="w-full max-w-[400px]">
        <div className="mb-5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-lg border border-border bg-surface text-fg"><ShieldCheck size={18} strokeWidth={1.75} aria-hidden="true" /></span>
            <div><p className="text-sm font-semibold tracking-tight text-fg">Veriforge</p><p className="text-xs text-fg-muted">Evidence-first workbench</p></div>
          </div>
          <ThemeToggle />
        </div>
        <section className="rounded-2xl border border-border bg-surface p-6 sm:p-8">
          <div className="mb-6">
            <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-border bg-sidebar px-2.5 py-1 text-[0.65rem] font-medium uppercase tracking-[0.12em] text-fg-muted"><Sparkles size={12} strokeWidth={1.75} className="text-fg" aria-hidden="true" /> Secure access</div>
            <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
            {description && <p className="mt-2 text-sm leading-6 text-fg-muted">{description}</p>}
          </div>
          {children}
        </section>
        {footer && <div className="mt-4 text-center text-xs text-fg-muted">{footer}</div>}
      </div>
    </main>
  )
}
