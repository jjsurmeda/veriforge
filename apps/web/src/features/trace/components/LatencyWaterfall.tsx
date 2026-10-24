import { Timer } from 'lucide-react'

import type { Metrics } from '../../../generated/types.gen'
import { formatMs } from '../format'

/** The pipeline's own order, not alphabetical. A waterfall that sorts by name
 *  reads as a list of words; one that follows the run reads as the run. Any
 *  stage the backend adds lands at the end rather than jumping the queue. */
const STAGE_ORDER = [
  'ingress+rewrite',
  'rewrite',
  'retrieve',
  'rerank',
  'sanitize',
  'evidence',
  'conflict',
  'generate',
  'review',
  'output_guard',
]

function stageLabel(key: string): string {
  // `ingress+rewrite` and `output_guard` are node keys, not prose; the panel
  // says "ingress rewrite".
  return key.replace(/_/g, ' ').replace('+', ' ')
}

function orderStages(keys: string[]): string[] {
  const known = STAGE_ORDER.filter((stage) => keys.includes(stage))
  const rest = keys.filter((key) => !STAGE_ORDER.includes(key)).sort()
  return [...known, ...rest]
}

/** TX-3: time by stage, plus time to first token.
 *
 *  The distinction the chart exists to make: `generate` is the generator's own
 *  loop, and everything above it is the wait a reader actually feels. So the
 *  pre-generate stages are drawn as one "before the first token" segment, with
 *  TTFT stated in words, and the stage bars beneath add up to the total.
 *
 *  Text equivalents throughout (design-system.md §9): every bar has its
 *  millisecond value beside it, and the whole figure is available as a
 *  sentence in the screen reader's `aria-label`.
 */
function StageRows({ keys, byKey, scale }: { keys: string[]; byKey: Map<string, number>; scale: number }) {
  return (
    <ul className="mt-1.5 space-y-1.5">
      {keys.map((key) => {
        const ms = byKey.get(key) ?? 0
        // Each group is scaled to its own slowest stage, so a 240 ms gate is
        // still a visible bar next to a 12 s generation instead of a 1 px sliver.
        const width = Math.max(3, Math.round((ms / scale) * 100))
        return (
          <li key={key} className="grid grid-cols-[minmax(0,7.5rem)_1fr_4rem] items-center gap-2 text-xs">
            <span className="truncate text-fg">{stageLabel(key)}</span>
            <span className="h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden="true">
              <span className="block h-full rounded-full bg-fg-strong" style={{ width: `${width}%` }} />
            </span>
            <span className="text-right font-mono text-2xs tabular-nums text-fg-muted">{formatMs(ms)}</span>
          </li>
        )
      })}
    </ul>
  )
}

function GroupHeading({ title, ms }: { title: string; ms: number }) {
  return (
    <p className="mt-3 flex items-baseline justify-between gap-2 text-2xs font-medium text-fg-muted">
      <span>{title}</span>
      <span className="font-mono tabular-nums">{formatMs(ms)}</span>
    </p>
  )
}

export function LatencyWaterfall({ metrics }: { metrics: Metrics }) {
  const entries = Object.entries(metrics.latency_ms ?? {})
  if (entries.length === 0) return null

  const stages = orderStages(entries.map(([key]) => key))
  const byKey = new Map(entries)
  const sum = (keys: string[]) => keys.reduce((total, key) => total + (byKey.get(key) ?? 0), 0)
  const total = sum(stages)
  if (total <= 0) return null

  const generateIndex = stages.indexOf('generate')
  const hasAnswer = generateIndex !== -1
  const before = hasAnswer ? stages.slice(0, generateIndex) : []
  const after = hasAnswer ? stages.slice(generateIndex) : stages
  const preGenerate = sum(before)
  const ttft = metrics.ttft_ms
  // TTFT is null for a run that produced no answer (a greeting, a library
  // listing, an abstention). It is then not 0 — there was no first token to
  // time — so the pre-generate segment is labelled by its own sum and no
  // "time to first token" number is claimed.
  const ttftKnown = ttft !== null && ttft !== undefined
  const waitMs = ttftKnown ? ttft : preGenerate
  const scaleOf = (keys: string[]) => Math.max(1, ...keys.map((key) => byKey.get(key) ?? 0))

  return (
    <section aria-labelledby="latency-waterfall-heading">
      <h3 id="latency-waterfall-heading" className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
        <Timer size={13} strokeWidth={1.75} aria-hidden="true" />
        Where the time went
      </h3>

      <div
        className="mt-2 flex h-2.5 w-full overflow-hidden rounded-full bg-sidebar"
        role="img"
        aria-label={
          hasAnswer && ttftKnown
            ? `Total ${formatMs(total)}. Time to first token ${formatMs(ttft)}: ${formatMs(preGenerate)} before the generator, ${formatMs(byKey.get('generate') ?? 0)} generating the answer.`
            : `Total ${formatMs(total)} across ${stages.length} stages.`
        }
      >
        {hasAnswer && <div className="h-full bg-fg-muted" style={{ width: `${(waitMs / total) * 100}%` }} />}
        <div className="h-full flex-1 bg-fg-strong" />
      </div>
      {hasAnswer && (
        <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-fg-muted" aria-hidden="true">
          <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-sm bg-fg-muted" />before the first token</span>
          <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-sm bg-fg-strong" />answer and review</span>
        </p>
      )}

      {hasAnswer && (
        <dl className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1 font-mono text-2xs tabular-nums">
          <dt className="text-fg-muted">Time to first token</dt>
          <dd className="text-fg">{ttftKnown ? formatMs(ttft) : 'not measured'}</dd>
        </dl>
      )}

      {hasAnswer && before.length > 0 && (
        <>
          <GroupHeading title="Before the first token" ms={preGenerate} />
          <StageRows keys={before} byKey={byKey} scale={scaleOf(before)} />
        </>
      )}
      <GroupHeading title={hasAnswer ? 'Answer and review' : 'Pipeline'} ms={sum(after)} />
      <StageRows keys={after} byKey={byKey} scale={scaleOf(after)} />
      <p className="mt-2 font-mono text-2xs tabular-nums text-fg-muted">total {formatMs(total)}</p>
    </section>
  )
}
