import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { CircleX, Gauge, ListTree, Maximize2, PanelRight } from 'lucide-react'

import { formatCredits } from '../../../lib/format'
import { PanelEmpty } from '../../../components/ui/PanelEmpty'
import { PanelError } from '../../../components/ui/PanelError'
import type { RunStatus } from '../../chat/store'
import type { Decision, MessageOut, Metrics, RetrievedChunk, RunStarted, StepCompleted, StepStarted } from '../../../generated/types.gen'
import { SourcesTab } from '../../chat/components/SourcesTab'
import { CitationsTab } from './CitationsTab'
import { DecisionSummary, DecisionTimeline } from './DecisionTimeline'
import { EvidenceGateCard } from './EvidenceGateCard'
import { LatencyWaterfall } from './LatencyWaterfall'
import { isGateDecision } from '../evidenceGates'
import { formatCount, formatMs } from '../format'
import { collapseSteps, type StepView } from '../stepsView'

interface Props {
  steps: Array<StepStarted | StepCompleted>
  decisions: Decision[]
  thinking: string
  streaming: boolean
  chunks: RetrievedChunk[]
  metrics: Metrics | null
  hold: boolean
  query?: string | null
  chatId: string | null
  viewerDocumentId: string | null
  open?: boolean
  expanded?: boolean
  activeTab?: TraceTab
  focusSource?: number | null
  onOpenChange?: (open: boolean) => void
  onExpandedChange?: (expanded: boolean) => void
  onTabChange?: (tab: TraceTab) => void
  onViewDocument?: (documentId: string) => void
  onCloseViewer?: () => void
  selectedMessage?: MessageOut | null
  scrollToTopSignal?: number
  /** The traced run's status, so an empty Trace can say whether nothing has
   *  run yet or the replay was lost. */
  traceStatus?: RunStatus | null
  onRetryTrace?: () => void
  /** The traced run's run.started event: mode, model and source. */
  started?: RunStarted | null
  /** Plain-language reason the traced run failed, or null. */
  failure?: string | null
}

export type TraceTab = 'sources' | 'citations' | 'trace' | 'metrics'

function StepRow({ step, streaming }: { step: StepView; streaming: boolean }) {
  return (
    <li className="flex items-baseline justify-between gap-2 border-b border-border/60 py-2 last:border-b-0">
      <span className="text-xs text-fg">{step.label}</span>
      <span className="font-mono text-2xs tabular-nums text-fg-muted">
        {step.durationMs !== null ? formatMs(step.durationMs) : streaming ? 'running' : 'no timing'}
      </span>
    </li>
  )
}

function SectionHeading({ id, children }: { id?: string; children: ReactNode }) {
  return <h3 id={id} className="mb-1.5 text-xs font-medium text-fg-muted">{children}</h3>
}

function StatTile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <p className="text-2xs text-fg-muted">{label}</p>
      <p className="mt-1 font-mono text-lg tabular-nums text-fg">{value}</p>
      {detail && <p className="mt-0.5 font-mono text-2xs tabular-nums text-fg-muted">{detail}</p>}
    </div>
  )
}

function capitalise(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

/** Which mode, model, source and reranker produced the run (F-5). Rows with
 *  no value are left out rather than printed as a dash. */
function RunInfo({ started, reranker }: { started: RunStarted | null | undefined; reranker: string | null }) {
  const rows: Array<[string, string]> = []
  if (started?.mode) rows.push(['Mode', capitalise(started.mode)])
  if (started?.model) rows.push(['Model', started.model])
  if (started?.source) rows.push(['Source', capitalise(started.source)])
  if (reranker) rows.push(['Reranker', reranker])
  if (rows.length === 0) return null
  return (
    <section aria-labelledby="run-info-heading">
      <SectionHeading id="run-info-heading">This run</SectionHeading>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border border-border bg-surface px-3 py-2.5">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-2xs text-fg-muted">{label}</dt>
            <dd className="min-w-0 break-words font-mono text-2xs text-fg">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function MetricsTab({ metrics, decisions, started, reranker }: { metrics: Metrics | null; decisions: Decision[]; started: RunStarted | null | undefined; reranker: string | null }) {
  const latency = Object.entries(metrics?.latency_ms ?? {})
  const total = latency.reduce((sum, [, ms]) => sum + ms, 0)
  const faithfulness = metrics?.faithfulness
  const minSupport = metrics?.min_support
  return (
    <div className="space-y-5 text-xs">
      <RunInfo started={started} reranker={reranker} />
      <div className="space-y-1.5">
        <DecisionSummary decisions={decisions} />
        <Link to="/decision-layer" className="inline-flex min-h-9 items-center text-xs text-fg underline decoration-fg-muted underline-offset-2 hover:decoration-fg focus-visible:outline-2 focus-visible:outline-focus-ring">
          System-wide decision layer
        </Link>
      </div>
      {!metrics ? (
        <PanelEmpty
          icon={<Gauge size={18} strokeWidth={1.75} aria-hidden="true" />}
          title="No metrics yet."
          hint="Latency, tokens, credits and scores land when the run completes."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <StatTile label="Total time" value={formatMs(total)} />
            <StatTile label="First token" value={metrics.ttft_ms !== null && metrics.ttft_ms !== undefined ? formatMs(metrics.ttft_ms) : 'not measured'} />
            <StatTile label="Tokens" value={formatCount((metrics.tokens_in ?? 0) + (metrics.tokens_out ?? 0))} detail={`${formatCount(metrics.tokens_in ?? 0)} in · ${formatCount(metrics.tokens_out ?? 0)} out`} />
            <StatTile label="Credits" value={metrics.credits !== undefined ? formatCredits(metrics.credits) : '—'} />
            <StatTile label="Faithfulness" value={faithfulness !== null && faithfulness !== undefined ? faithfulness.toFixed(2) : '—'} detail={minSupport !== null && minSupport !== undefined ? `min support ${minSupport.toFixed(2)}` : undefined} />
            <StatTile label="Context used" value={formatCount(metrics.context_used ?? 0)} detail={`of ${formatCount(metrics.context_window ?? 0)}`} />
          </div>
          <LatencyWaterfall metrics={metrics} />
        </>
      )}
    </div>
  )
}

export function TracePanel({ steps: rawSteps, decisions, thinking, streaming, chunks, metrics, hold, query, chatId, viewerDocumentId, open, expanded, activeTab, focusSource, onOpenChange, onExpandedChange, onTabChange, onViewDocument, onCloseViewer, selectedMessage, scrollToTopSignal, traceStatus, onRetryTrace, started, failure }: Props) {
  const [internalOpen, setInternalOpen] = useState(true)
  const [internalExpanded, setInternalExpanded] = useState(false)
  const [internalTab, setInternalTab] = useState<TraceTab>('trace')
  const bodyRef = useRef<HTMLDivElement>(null)
  const isOpen = open ?? internalOpen
  const isExpanded = expanded ?? internalExpanded
  const tab = activeTab ?? internalTab

  useEffect(() => {
    if (scrollToTopSignal === undefined) return
    bodyRef.current?.scrollTo({ top: 0 })
  }, [scrollToTopSignal])

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
    if (focusSource === null || focusSource === undefined || tab !== 'citations' || !isOpen) return
    const target = document.getElementById(`trace-source-${focusSource}`)
    target?.scrollIntoView({ block: 'center' })
  }, [focusSource, isOpen, tab])

  const citedCount = selectedMessage?.citations?.length ?? chunks.length
  const tabs: Array<{ id: TraceTab; label: string }> = [
    { id: 'sources', label: 'Sources' },
    { id: 'citations', label: `Citations${citedCount ? ` (${citedCount})` : ''}` },
    { id: 'trace', label: 'Trace' },
    { id: 'metrics', label: 'Metrics' },
  ]
  const tracedRunId = started?.run_id
  const reranker = typeof selectedMessage?.metrics?.reranker === 'string' && (!tracedRunId || !selectedMessage.run_id || selectedMessage.run_id === tracedRunId) ? selectedMessage.metrics.reranker : null
  const steps = collapseSteps(rawSteps)
  const timelineDecisions = decisions.filter((decision) => !isGateDecision(decision))

  return (
    <>
      {isOpen && <button type="button" aria-label="Close workspace panel" onClick={() => setOpen(false)} className="fixed inset-0 z-30 bg-main/70 xl:hidden" />}
      <aside aria-label="Evidence workspace" className={`${isOpen ? 'flex' : 'hidden'} ${isExpanded ? 'xl:w-[min(50vw,640px)]' : 'xl:w-[400px]'} fixed inset-y-0 right-0 z-40 w-[min(100vw,400px)] shrink-0 flex-col border-l border-border bg-sidebar text-fg xl:static xl:z-auto`}>
        <header className="flex min-h-14 shrink-0 items-center justify-between gap-1 border-b border-border px-2">
          <nav className="flex min-w-0 items-center gap-0.5" aria-label="Trace tabs" role="tablist">
            {tabs.map((item, index) => (
              <button key={item.id} id={`workspace-tab-${item.id}`} type="button" role="tab" aria-selected={tab === item.id} aria-controls={`workspace-${item.id}`} tabIndex={tab === item.id ? 0 : -1} onClick={() => setTab(item.id)} onKeyDown={(event) => { if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return; event.preventDefault(); const nextIndex = event.key === 'ArrowRight' ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length; const next = tabs[nextIndex]; setTab(next.id); document.getElementById(`workspace-tab-${next.id}`)?.focus() }} className={`inline-flex min-h-9 items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 text-xs transition-[background-color,color] duration-150 focus-visible:outline-2 focus-visible:outline-focus-ring ${tab === item.id ? 'bg-raised font-medium text-fg' : 'text-fg-muted hover:bg-raised-hover hover:text-fg'}`}>
                {item.label}
                {item.id === 'trace' && streaming && <span className="size-1.5 animate-pulse rounded-full bg-fg-strong motion-reduce:animate-none" role="img" aria-label="live" />}
              </button>
            ))}
          </nav>
          <div className="flex shrink-0 items-center gap-0.5">
            <button type="button" aria-label={isExpanded ? 'Restore workspace panel width' : 'Expand workspace panel'} aria-pressed={isExpanded} onClick={() => setExpanded(!isExpanded)} className="icon-button hidden size-8 xl:inline-flex"><Maximize2 size={15} strokeWidth={1.75} aria-hidden="true" /></button>
            <button type="button" aria-label="Collapse workspace panel" onClick={() => setOpen(false)} className="icon-button size-8"><PanelRight size={16} strokeWidth={1.75} aria-hidden="true" /></button>
          </div>
        </header>
        {hold && <p className="border-b border-border/20 bg-raised px-4 py-2 text-xs text-warning" role="status">Verifying… the reviewed answer lands when checks finish.</p>}
        <div ref={bodyRef} className={`min-h-0 flex-1 overflow-y-auto ${tab === 'sources' ? 'flex flex-col overflow-hidden p-0' : 'px-4 py-4'}`}>
          {tab === 'sources' && <div id="workspace-sources" role="tabpanel" className="flex min-h-0 flex-1 flex-col"><SourcesTab chatId={chatId} viewerDocumentId={viewerDocumentId} onViewDocument={(documentId) => onViewDocument?.(documentId)} onCloseViewer={() => onCloseViewer?.()} /></div>}
          {tab === 'citations' && <div id="workspace-citations" role="tabpanel"><CitationsTab chunks={chunks} message={selectedMessage} query={query} onOpenDocument={onViewDocument} /></div>}
          {tab === 'trace' && <div id="workspace-trace" role="tabpanel" className="space-y-5">
            {failure && <p className="flex items-start gap-2 rounded-lg border border-danger/40 bg-surface px-3 py-2.5 text-xs text-danger"><CircleX size={14} strokeWidth={1.75} className="mt-px shrink-0" aria-hidden="true" /><span>This run failed. {failure}</span></p>}
            {thinking.length > 0 && <section><details><summary className="cursor-pointer text-xs font-medium text-fg-muted hover:text-fg">Thinking</summary><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-fg-muted">{thinking}</p></details></section>}
            {steps.length > 0 && <section aria-labelledby="trace-steps-heading"><SectionHeading id="trace-steps-heading">Steps</SectionHeading><ul>{steps.map((step, index) => <StepRow key={index} step={step} streaming={streaming} />)}</ul></section>}
            <EvidenceGateCard decisions={decisions} />
            {timelineDecisions.length > 0 && <section aria-labelledby="decision-timeline-heading"><SectionHeading id="decision-timeline-heading">Decisions by stage</SectionHeading><DecisionTimeline decisions={timelineDecisions} /></section>}
            {steps.length === 0 && decisions.length === 0 && thinking.length === 0 && !failure && (
              // Item 6: a dropped replay leaves the same empty arrays as a
              // chat that has never run, so "No run yet." was a confident
              // wrong answer about a run that exists.
              traceStatus === 'connection_lost' ? (
                <PanelError
                  title="This trace could not be replayed."
                  hint="The connection dropped before its steps arrived. The answer and its sources are unaffected."
                  action={
                    onRetryTrace && (
                      <button
                        type="button"
                        onClick={onRetryTrace}
                        className="pressable min-h-9 w-full rounded-lg border border-border bg-surface px-3 text-xs text-fg hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring"
                      >
                        Reconnect
                      </button>
                    )
                  }
                />
              ) : (
                <PanelEmpty
                  icon={<ListTree size={18} strokeWidth={1.75} aria-hidden="true" />}
                  title="No run yet."
                  hint="Decisions and reasoning stream here while a run is in flight."
                />
              )
            )}
          </div>}
          {tab === 'metrics' && <div id="workspace-metrics" role="tabpanel"><MetricsTab metrics={metrics} decisions={decisions} started={started} reranker={reranker} /></div>}
        </div>
      </aside>
    </>
  )
}
