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
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-10 text-foreground sm:px-6">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-32 -top-32 size-[30rem] rounded-full bg-primary-soft blur-3xl" />
        <div className="absolute -bottom-40 -right-24 size-[28rem] rounded-full bg-secondary-soft blur-3xl" />
        <div className="absolute right-[18%] top-[12%] size-24 rounded-full border border-accent/15" />
      </div>
      <div className="relative z-10 w-full max-w-md">
        <div className="mb-6 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-xl bg-primary text-on-primary shadow-md">
              <ShieldCheck size={20} aria-hidden="true" />
            </span>
            <div>
              <p className="font-display text-base font-semibold tracking-tight text-foreground">Veriforge</p>
              <p className="text-xs text-muted-foreground">Evidence-first workbench</p>
            </div>
          </div>
          <ThemeToggle />
        </div>
        <section className="rounded-xl border border-border bg-surface p-6 shadow-lg sm:p-8">
          <div className="mb-6">
            <div className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 font-mono text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-accent">
              <Sparkles size={12} aria-hidden="true" />
              Secure access
            </div>
            <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
            {description && <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>}
          </div>
          {children}
        </section>
        {footer && <div className="mt-4 text-center text-xs text-muted-foreground">{footer}</div>}
      </div>
    </main>
  )
}
