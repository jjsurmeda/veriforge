import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, History, ShieldCheck } from 'lucide-react'

import { decisionStatsAdminDecisionsStatsGet, publicDecisionStatsDecisionsStatsGet } from '../../generated/sdk.gen'
import type { DecisionStatsOut } from '../../generated/types.gen'
import { PanelEmpty } from '../../components/ui/PanelEmpty'

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
      <div className="text-2xs text-fg-muted">{label}</div>
      <div className="mt-1 flex items-baseline justify-between gap-2">
        <span className="font-mono text-lg tabular-nums text-fg">{value}</span>
        {pass !== undefined && (
          <span className={`inline-flex items-center gap-1 text-2xs ${pass ? 'text-success' : 'text-danger'}`}>
            {pass ? <CheckCircle2 size={12} aria-hidden="true" /> : <AlertTriangle size={12} aria-hidden="true" />}
            {pass ? 'pass' : 'fail'}
          </span>
        )}
      </div>
      {target && <div className="mt-1 font-mono text-2xs tabular-nums text-fg-muted">target {target}</div>}
    </div>
  )
}

function BreakerStatus({ stats }: { stats: DecisionStatsOut }) {
  const state = stats.breaker.state
  const tone = state === 'closed' ? 'success' : state === 'open' ? 'danger' : 'warning'
  const toneClass = {
    success: 'border-border/30 bg-raised text-success',
    danger: 'border-border/30 bg-raised text-danger',
    warning: 'border-border/30 bg-raised text-warning',
  }[tone]
  return (
    <section className="rounded-xl border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-sidebar/60 px-4 py-3">
        <h2 className="flex items-center gap-2 text-xs font-semibold text-fg">
          <ShieldCheck size={13} className="text-fg" aria-hidden="true" />
          Circuit breaker
        </h2>
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${toneClass}`}>
          {state === 'closed' ? <CheckCircle2 size={12} aria-hidden="true" /> : <AlertTriangle size={12} aria-hidden="true" />}
          {state.replace('_', ' ')}
        </span>
      </div>
      <div className="px-4 py-3 text-xs text-fg-muted">
        {stats.breaker.open_until ? `Probe allowed after ${new Date(stats.breaker.open_until).toLocaleTimeString()}` : 'No active cooldown.'}
      </div>
    </section>
  )
}

/** The one decision-layer panel (audit F-32), used by the Decision layer page
 *  and by Admin.
 *
 *  Read-only throughout: the one control (the window select) only changes the
 *  query. `admin` switches the source to the admin route, which is the only one
 *  that carries `recent_disagreements` (run ids of other users); every other
 *  signed-in user reads `/decisions/stats`, aggregates only.
 *
 *  Real numbers only. Every tile is a measured value or an explicit "no data
 *  yet": no sparkline, no placeholder bar. Vocabulary follows the README:
 *  Jev answers, the LLM judge is the fallback behind the circuit breaker.
 */
export function DecisionLayerPanel({ admin = false }: { admin?: boolean }) {
  const [hours, setHours] = useState(24)
  const stats = useQuery({
    queryKey: [admin ? 'admin' : 'decisions', 'decision-stats', hours],
    queryFn: async () => {
      const { data, error } = admin
        ? await decisionStatsAdminDecisionsStatsGet({ query: { hours } })
        : await publicDecisionStatsDecisionsStatsGet({ query: { hours } })
      if (error) throw error
      return data
    },
  })

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-fg">
            <Activity size={17} className="text-fg" aria-hidden="true" />
            Decision layer
          </h2>
          <p className="mt-1 text-xs text-fg-muted">Jev throughput, how often the LLM judge had to step in, and Jev-versus-judge agreement.</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-fg-muted">
          Window
          <select
            aria-label="Decision stats window"
            className="h-9 rounded-lg border border-border bg-main px-2.5 text-xs text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
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
        <div className="rounded-xl border border-border bg-surface p-5 text-sm text-fg-muted" role="status">
          Loading decision statistics…
        </div>
      )}
      {stats.isError && (
        <div className="rounded-xl border border-border/30 bg-raised p-4 text-sm text-danger" role="alert">
          Decision statistics could not be loaded.
        </div>
      )}
      {stats.data && (
        <>
          {stats.data.total === 0 ? (
            <PanelEmpty
              icon={<Activity size={18} strokeWidth={1.75} aria-hidden="true" />}
              title="No decisions in this window yet."
              hint="These numbers appear once runs have used the decision engine. Nothing is estimated before then."
            />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <StatTile label="Decisions" value={String(stats.data.total)} />
                <StatTile label="Jev answers" value={`${stats.data.jev_count}/${stats.data.total}`} />
                <StatTile
                  label="Judge fallback share"
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
                <StatTile label="Rerank p50" value={formatMs(stats.data.rerank_latency_p50_ms ?? null)} />
                <StatTile label="Rerank p95" value={formatMs(stats.data.rerank_latency_p95_ms ?? null)} />
              </div>

              <BreakerStatus stats={stats.data} />

              <div className="grid gap-4 xl:grid-cols-2">
                <section className="overflow-hidden rounded-xl border border-border bg-surface">
                  <h2 className="border-b border-border bg-sidebar/60 px-4 py-3 text-xs font-semibold text-fg">
                    Decisions by name
                  </h2>
                  {stats.data.by_decision.length === 0 ? (
                    <p className="px-4 py-5 text-sm text-fg-muted">No decision events in this window.</p>
                  ) : (
                    <div className="divide-y divide-border/70">
                      {stats.data.by_decision.map((row) => (
                        <div key={row.name_or_prefix} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 px-4 py-2.5 text-xs">
                          <span className="truncate font-mono text-fg">{row.name_or_prefix}</span>
                          <span className="font-mono tabular-nums text-fg-muted">{row.count}</span>
                          <span className="font-mono text-warning">{row.fallback_count} judge</span>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                <section className="overflow-hidden rounded-xl border border-border bg-surface">
                  <h2 className="flex items-center gap-2 border-b border-border bg-sidebar/60 px-4 py-3 text-xs font-semibold text-fg">
                    <History size={13} className="text-fg" aria-hidden="true" />
                    Jev vs judge agreement · {formatShare(stats.data.shadow.agree_rate)} ({stats.data.shadow.sampled} sampled)
                  </h2>
                  {stats.data.shadow.sampled === 0 ? (
                    <p className="px-4 py-5 text-sm text-fg-muted">
                      Nothing sampled yet. Shadow mode has the LLM judge answer a small share of decisions a second time, and this is
                      what it saw.
                    </p>
                  ) : !admin ? (
                    <p className="px-4 py-5 text-sm text-fg-muted">Individual disagreements are visible to administrators only.</p>
                  ) : stats.data.shadow.recent_disagreements.length === 0 ? (
                    <p className="px-4 py-5 text-sm text-fg-muted">No recent disagreements.</p>
                  ) : (
                    <ul className="divide-y divide-border/70">
                      {stats.data.shadow.recent_disagreements.map((row) => (
                        <li key={`${row.run_id}-${row.decision}-${row.created_at}`} className="space-y-2 px-4 py-3 text-xs">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-mono font-medium text-fg">{row.decision}</span>
                            <span className="font-mono text-2xs text-fg-muted">{new Date(row.created_at).toLocaleString()}</span>
                          </div>
                          <div className="grid gap-2 sm:grid-cols-2">
                            <div className="rounded-md border border-border/20 bg-raised px-2.5 py-2">
                              <div className="font-mono text-2xs uppercase tracking-wide text-fg">Jev</div>
                              <div className="mt-1 font-mono text-fg">{answerSummary(row.jev_answer)}</div>
                            </div>
                            <div className="rounded-md border border-border/20 bg-raised px-2.5 py-2">
                              <div className="font-mono text-2xs uppercase tracking-wide text-warning">LLM judge</div>
                              <div className="mt-1 font-mono text-fg">{answerSummary(row.fallback_answer)}</div>
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
        </>
      )}
    </section>
  )
}
