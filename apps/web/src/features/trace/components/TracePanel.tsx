import { useEffect, useState, type ReactNode } from 'react'
import { Gauge, ListTree, Maximize2, PanelRight, Quote } from 'lucide-react'

import { formatCredits } from '../../../lib/format'
import type { Decision, Metrics, RetrievedChunk, StepCompleted, StepStarted } from '../../../generated/types.gen'
import { SourcesTab } from './SourcesTab'
import { DecisionSummary, DecisionTimeline } from './DecisionTimeline'

interface Props {
  steps: Array<StepStarted | StepCompleted>
  decisions: Decision[]
  thinking: string
  streaming: boolean
  chunks: RetrievedChunk[]
  metrics: Metrics | null
  hold: boolean
  query?: string | null
  open?: boolean
  expanded?: boolean
  activeTab?: TraceTab
  focusSource?: number | null
  onOpenChange?: (open: boolean) => void
  onExpandedChange?: (expanded: boolean) => void
  onTabChange?: (tab: TraceTab) => void
  onOpenDocument?: (documentId: string) => void
}

export type TraceTab = 'trace' | 'sources' | 'metrics'

function StepRow({ step }: { step: StepStarted | StepCompleted }) {
  const isCompleted = step.type === 'step.completed'
  return (
    <li className="flex items-baseline justify-between gap-2 border-b border-border/60 py-2 last:border-b-0">
      <span className="text-xs text-foreground">{step.label}</span>
      <span className="font-mono text-[0.65rem] tabular-nums text-muted-foreground">{isCompleted ? `${(step as StepCompleted).duration_ms} ms` : '…'}</span>
    </li>
  )
}

function WaterfallRow({ label, ms, max }: { label: string; ms: number; max: number }) {
  const width = max > 0 ? Math.max(2, Math.round((ms / max) * 100)) : 0
  return (
    <li className="py-1.5">
      <div className="flex items-baseline justify-between gap-2 text-xs"><span className="text-foreground">{label}</span><span className="font-mono tabular-nums text-muted-foreground">{ms} ms</span></div>
      <div className="mt-1 h-1.5 w-full rounded-full bg-surface-raised"><div className="h-1.5 rounded-full bg-accent" style={{ width: `${width}%` }} /></div>
    </li>
  )
}

function StatTile({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-border bg-surface px-3 py-2.5"><p className="text-[0.62rem] text-muted-foreground">{label}</p><p className="mt-1 font-mono text-lg tabular-nums text-foreground">{value}</p></div>
}

function MetricsTab({ metrics, decisions }: { metrics: Metrics | null; decisions: Decision[] }) {
  const latency = Object.entries(metrics?.latency_ms ?? {})
  const max = Math.max(1, ...latency.map(([, ms]) => ms))
  const total = latency.reduce((sum, [, ms]) => sum + ms, 0)
  const tokens = (metrics?.tokens_in ?? 0) + (metrics?.tokens_out ?? 0)
  return (
    <div className="space-y-5 text-xs">
      <DecisionSummary decisions={decisions} />
      {!metrics ? (
        <p className="py-8 text-center text-muted-foreground">Metrics land when the run completes.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <StatTile label="Latency" value={`${total} ms`} />
            <StatTile label="Tokens" value={String(tokens)} />
            <StatTile label="Credits" value={metrics.credits !== undefined ? formatCredits(metrics.credits) : '—'} />
            <StatTile label="Faithfulness" value={metrics.faithfulness !== null && metrics.faithfulness !== undefined ? metrics.faithfulness.toFixed(2) : '—'} />
            <StatTile label="Stages" value={String(latency.length)} />
          </div>
          <section>
            <h3 className="text-xs font-medium text-muted-foreground">Latency by stage</h3>
            <ul className="mt-1">{latency.map(([label, ms]) => <WaterfallRow key={label} label={label} ms={ms} max={max} />)}</ul>
            <p className="mt-1 font-mono tabular-nums text-muted-foreground">total {total} ms</p>
          </section>
          <section>
            <h3 className="text-xs font-medium text-muted-foreground">Answer scores</h3>
            <ul className="mt-1 space-y-0.5 font-mono tabular-nums text-muted-foreground"><li>faithfulness {metrics.faithfulness !== null && metrics.faithfulness !== undefined ? metrics.faithfulness.toFixed(2) : '—'}</li><li>min support {metrics.min_support !== null && metrics.min_support !== undefined ? metrics.min_support.toFixed(2) : '—'}</li></ul>
          </section>
          <section>
            <h3 className="text-xs font-medium text-muted-foreground">Usage</h3>
            <ul className="mt-1 space-y-0.5 font-mono tabular-nums text-muted-foreground"><li>tokens in {metrics.tokens_in}</li><li>tokens out {metrics.tokens_out}</li><li>credits {metrics.credits !== undefined ? formatCredits(metrics.credits) : '—'}</li><li>context {metrics.context_used} / {metrics.context_window}</li></ul>
          </section>
        </>
      )}
    </div>
  )
}

export function TracePanel({ steps, decisions, thinking, streaming, chunks, metrics, hold, query, open, expanded, activeTab, focusSource, onOpenChange, onExpandedChange, onTabChange, onOpenDocument }: Props) {
  const [internalOpen, setInternalOpen] = useState(true)
  const [internalExpanded, setInternalExpanded] = useState(false)
  const [internalTab, setInternalTab] = useState<TraceTab>('trace')
  const isOpen = open ?? internalOpen
  const isExpanded = expanded ?? internalExpanded
  const tab = activeTab ?? internalTab

  const setOpen = (next: boolean) => {
    setInternalOpen(next)
    onOpenChange?.(next)
  }
  const setExpanded = (next: boolean) => {
    setInternalExpanded(next)
    onExpandedChange?.(next)
  }
  const setTab = (next: TraceTab) => {
    setInternalTab(next)
    onTabChange?.(next)
  }

  useEffect(() => {
    if (focusSource === null || focusSource === undefined || tab !== 'sources' || !isOpen) return
    const target = document.getElementById(`trace-source-${focusSource}`)
    target?.scrollIntoView({ block: 'center' })
  }, [focusSource, isOpen, tab])

  const tabs: Array<{ id: TraceTab; label: string; icon: ReactNode }> = [
    { id: 'trace', label: 'Trace', icon: <ListTree size={14} strokeWidth={1.75} aria-hidden="true" /> },
    { id: 'sources', label: `Sources${chunks.length > 0 ? ` (${chunks.length})` : ''}`, icon: <Quote size={14} strokeWidth={1.75} aria-hidden="true" /> },
    { id: 'metrics', label: 'Metrics', icon: <Gauge size={14} strokeWidth={1.75} aria-hidden="true" /> },
  ]

  return (
    <>
      {isOpen && <button type="button" aria-label="Close workspace panel" onClick={() => setOpen(false)} className="fixed inset-0 z-30 bg-background/70 xl:hidden" />}
      <aside aria-label="Evidence workspace" className={`${isOpen ? 'flex' : 'hidden'} ${isExpanded ? 'xl:w-[min(50vw,640px)]' : 'xl:w-[400px]'} fixed inset-y-0 right-0 z-40 w-[min(100vw,400px)] shrink-0 flex-col border-l border-border bg-surface-muted text-foreground xl:static xl:z-auto`}>
        <header className="flex min-h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-3">
          <nav className="flex min-w-0 items-center gap-0.5" aria-label="Trace tabs" role="tablist">
            {tabs.map((item, index) => (
              <button key={item.id} id={`workspace-tab-${item.id}`} type="button" aria-selected={tab === item.id} aria-controls={`workspace-${item.id}`} tabIndex={tab === item.id ? 0 : -1} onClick={() => setTab(item.id)} onKeyDown={(event) => { if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return; event.preventDefault(); const nextIndex = event.key === 'ArrowRight' ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length; const next = tabs[nextIndex]; setTab(next.id); document.getElementById(`workspace-tab-${next.id}`)?.focus() }} className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg px-2 text-xs transition-[background-color,color] duration-150 focus-visible:outline-2 focus-visible:outline-accent ${tab === item.id ? 'bg-surface-raised font-medium text-foreground' : 'text-muted-foreground hover:bg-surface-hover hover:text-foreground'}`}>
                {item.icon}<span className="hidden sm:inline">{item.label}</span>
              </button>
            ))}
          </nav>
          <div className="flex shrink-0 items-center gap-0.5">
            {streaming && <span className="mr-1 inline-flex items-center gap-1.5 text-[0.65rem] text-accent"><span className="size-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />live</span>}
            <button type="button" aria-label={isExpanded ? 'Restore workspace panel width' : 'Expand workspace panel'} aria-pressed={isExpanded} onClick={() => setExpanded(!isExpanded)} className="icon-button size-8"><Maximize2 size={15} strokeWidth={1.75} aria-hidden="true" /></button>
            <button type="button" aria-label="Collapse workspace panel" onClick={() => setOpen(false)} className="icon-button size-8"><PanelRight size={16} strokeWidth={1.75} aria-hidden="true" /></button>
          </div>
        </header>
        {hold && <p className="border-b border-warning/20 bg-warning-soft px-4 py-2 text-xs text-warning" role="status">Verifying… the reviewed answer lands when checks finish.</p>}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {tab === 'trace' && <div id="workspace-trace" role="tabpanel" className="space-y-5">
            {thinking.length > 0 && <section><details><summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">Thinking</summary><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">{thinking}</p></details></section>}
            {steps.length > 0 && <section><h3 className="mb-1 text-xs font-medium text-muted-foreground">Steps</h3><ul>{steps.map((step, index) => <StepRow key={index} step={step} />)}</ul></section>}
            {decisions.length > 0 && <section aria-labelledby="decision-timeline-heading"><h3 id="decision-timeline-heading" className="mb-2 text-xs font-medium text-muted-foreground">Decision timeline</h3><DecisionTimeline decisions={decisions} /></section>}
            {steps.length === 0 && decisions.length === 0 && thinking.length === 0 && <p className="py-8 text-center text-muted-foreground">Decisions and reasoning stream here while a run is in flight.</p>}
          </div>}
          {tab === 'sources' && <div id="workspace-sources" role="tabpanel"><SourcesTab chunks={chunks} query={query} onOpenDocument={onOpenDocument} /></div>}
          {tab === 'metrics' && <div id="workspace-metrics" role="tabpanel"><MetricsTab metrics={metrics} decisions={decisions} /></div>}
        </div>
      </aside>
    </>
  )
}
