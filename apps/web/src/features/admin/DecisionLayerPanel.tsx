import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, CheckCircle2, History, ShieldCheck } from 'lucide-react'
import { useState } from 'react'

import { decisionStatsAdminDecisionsStatsGet } from '../../generated/sdk.gen'
import type { DecisionStatsOut } from '../../generated/types.gen'

const WINDOWS = [
  { hours: 1, label: '1h' },
  { hours: 24, label: '24h' },
  { hours: 168, label: '7d' },
]

function formatMs(value: number | null): string {
  return value === null ? '—' : `${Math.round(value)} ms`
}

function formatShare(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

function answerSummary(answer: Record<string, unknown>): string {
  const value = answer.value
  if (typeof value === 'number') return value.toFixed(2)
  if (typeof value === 'string') return value
  return value === undefined ? '—' : JSON.stringify(value)
}

function StatTile({
  label,
  value,
  target,
  pass,
}: {
  label: string
  value: string
  target?: string
  pass?: boolean
}) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <div className="text-[0.62rem] text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline justify-between gap-2">
        <span className="font-mono text-lg text-foreground">{value}</span>
        {pass !== undefined && (
          <span className={`inline-flex items-center gap-1 text-[0.65rem] ${pass ? 'text-success' : 'text-danger'}`}>
            {pass ? <CheckCircle2 size={12} aria-hidden="true" /> : <AlertTriangle size={12} aria-hidden="true" />}
            {pass ? 'pass' : 'fail'}
          </span>
        )}
      </div>
      {target && <div className="mt-1 font-mono text-[0.6rem] text-muted-foreground">target {target}</div>}
    </div>
  )
}

function BreakerStatus({ stats }: { stats: DecisionStatsOut }) {
  const state = stats.breaker.state
  const tone = state === 'closed' ? 'success' : state === 'open' ? 'danger' : 'warning'
  const toneClass = {
    success: 'border-success/30 bg-success-soft text-success',
    danger: 'border-danger/30 bg-danger-soft text-danger',
    warning: 'border-warning/30 bg-warning-soft text-warning',
  }[tone]
  return (
    <section className="rounded-xl border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface-muted/60 px-4 py-3">
        <h2 className="flex items-center gap-2 text-xs font-semibold text-foreground">
          <ShieldCheck size={13} className="text-accent" aria-hidden="true" />
          Circuit breaker
        </h2>
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${toneClass}`}>
          {state === 'closed' ? <CheckCircle2 size={12} aria-hidden="true" /> : <AlertTriangle size={12} aria-hidden="true" />}
          {state.replace('_', ' ')}
        </span>
      </div>
      <div className="px-4 py-3 text-xs text-muted-foreground">
        {stats.breaker.open_until ? `Probe allowed after ${new Date(stats.breaker.open_until).toLocaleTimeString()}` : 'No active cooldown.'}
      </div>
    </section>
  )
}

export function DecisionLayerPanel() {
  const [hours, setHours] = useState(24)
  const stats = useQuery({
    queryKey: ['admin', 'decision-stats', hours],
    queryFn: async () => {
      const { data, error } = await decisionStatsAdminDecisionsStatsGet({ query: { hours } })
      if (error) throw error
      return data
    },
  })

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            <Activity size={17} className="text-accent" aria-hidden="true" />
            Decision layer
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">Jev throughput, fallback pressure, and shadow agreement.</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Window
          <select
            aria-label="Decision stats window"
            className="h-9 rounded-lg border border-border bg-background px-2.5 text-xs text-foreground focus-visible:outline-2 focus-visible:outline-primary"
            value={hours}
            onChange={(event) => setHours(Number(event.target.value))}
          >
            {WINDOWS.map((window) => (
              <option key={window.hours} value={window.hours}>{window.label}</option>
            ))}
          </select>
        </label>
      </div>

      {stats.isPending && (
        <div className="rounded-xl border border-border bg-surface p-5 text-sm text-muted-foreground" role="status">
          Loading decision statistics…
        </div>
      )}
      {stats.isError && (
        <div className="rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger" role="alert">
          Decision statistics could not be loaded.
        </div>
      )}
      {stats.data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <StatTile label="Decisions" value={String(stats.data.total)} />
            <StatTile label="Jev answers" value={`${stats.data.jev_count}/${stats.data.total}`} />
            <StatTile
              label="Fallback share"
              value={formatShare(stats.data.fallback_share)}
              target={formatShare(stats.data.targets.fallback_share)}
              pass={stats.data.fallback_share <= stats.data.targets.fallback_share}
            />
            <StatTile
              label="Ingress p95"
              value={formatMs(stats.data.ingress_p95_ms)}
              target={formatMs(stats.data.targets.ingress_p95_ms)}
              pass={stats.data.ingress_p95_ms === null || stats.data.ingress_p95_ms <= stats.data.targets.ingress_p95_ms}
            />
            <StatTile label="Jev p50" value={formatMs(stats.data.jev_latency_p50_ms)} />
            <StatTile label="Jev p95" value={formatMs(stats.data.jev_latency_p95_ms)} />
          </div>

          <BreakerStatus stats={stats.data} />

          <div className="grid gap-4 xl:grid-cols-2">
            <section className="overflow-hidden rounded-xl border border-border bg-surface">
              <h2 className="border-b border-border bg-surface-muted/60 px-4 py-3 text-xs font-semibold text-foreground">
                Decisions by name
              </h2>
              {stats.data.by_decision.length === 0 ? (
                <p className="px-4 py-5 text-sm text-muted-foreground">No decision events in this window.</p>
              ) : (
                <div className="divide-y divide-border/70">
                  {stats.data.by_decision.map((row) => (
                    <div key={row.name_or_prefix} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 px-4 py-2.5 text-xs">
                      <span className="truncate font-mono text-foreground">{row.name_or_prefix}</span>
                      <span className="font-mono text-muted-foreground">{row.count}</span>
                      <span className="font-mono text-warning">{row.fallback_count} fallback</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="overflow-hidden rounded-xl border border-border bg-surface">
              <h2 className="flex items-center gap-2 border-b border-border bg-surface-muted/60 px-4 py-3 text-xs font-semibold text-foreground">
                <History size={13} className="text-accent" aria-hidden="true" />
                Shadow agreement · {formatShare(stats.data.shadow.agree_rate)} ({stats.data.shadow.sampled} sampled)
              </h2>
              {stats.data.shadow.recent_disagreements.length === 0 ? (
                <p className="px-4 py-5 text-sm text-muted-foreground">No recent disagreements.</p>
              ) : (
                <ul className="divide-y divide-border/70">
                  {stats.data.shadow.recent_disagreements.map((row) => (
                    <li key={`${row.run_id}-${row.decision}-${row.created_at}`} className="space-y-2 px-4 py-3 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono font-medium text-foreground">{row.decision}</span>
                        <span className="font-mono text-[0.6rem] text-muted-foreground">{new Date(row.created_at).toLocaleString()}</span>
                      </div>
                      <div className="grid gap-2 sm:grid-cols-2">
                        <div className="rounded-md border border-accent/20 bg-accent-soft px-2.5 py-2">
                          <div className="font-mono text-[0.6rem] uppercase tracking-wide text-accent">Jev</div>
                          <div className="mt-1 font-mono text-foreground">{answerSummary(row.jev_answer)}</div>
                        </div>
                        <div className="rounded-md border border-warning/20 bg-warning-soft px-2.5 py-2">
                          <div className="font-mono text-[0.6rem] uppercase tracking-wide text-warning">Fallback</div>
                          <div className="mt-1 font-mono text-foreground">{answerSummary(row.fallback_answer)}</div>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </section>
  )
}
