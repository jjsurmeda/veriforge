import { ArrowRight, Timer } from 'lucide-react'

import type { Metrics } from '../../../generated/types.gen'

/** The pipeline's own order, not alphabetical. A waterfall that sorts by name
 *  reads as a list of words; one that follows the run reads as the run. Any
 *  stage the backend adds lands at the end rather than jumping the queue. */
const STAGE_ORDER = [
  'ingress+rewrite',
  'rewrite',
  'retrieve',
  'rerank',
  'sanitize',
  'sufficient',
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
export function LatencyWaterfall({ metrics }: { metrics: Metrics }) {
  const entries = Object.entries(metrics.latency_ms ?? {})
  if (entries.length === 0) return null

  const stages = orderStages(entries.map(([key]) => key))
  const byKey = new Map(entries)
  const total = stages.reduce((sum, key) => sum + (byKey.get(key) ?? 0), 0)
  if (total <= 0) return null

  const generateIndex = stages.indexOf('generate')
  const preGenerate = stages
    .slice(0, generateIndex === -1 ? stages.length : generateIndex)
    .reduce((sum, key) => sum + (byKey.get(key) ?? 0), 0)
  const ttft = metrics.ttft_ms
  // TTFT is null for a run that produced no answer (a greeting, a library
  // listing, an abstention). It is then not 0 — there was no first token to
  // time — so the pre-generate segment is labelled by its own sum and no
  // "time to first token" number is claimed.
  const hasAnswer = generateIndex !== -1
  const ttftKnown = ttft !== null && ttft !== undefined
  const waitMs = ttftKnown ? ttft : preGenerate

  return (
    <section aria-labelledby="latency-waterfall-heading">
      <h3
        id="latency-waterfall-heading"
        className="flex items-center gap-1.5 text-xs font-medium text-fg-muted"
      >
        <Timer size={13} strokeWidth={1.75} aria-hidden="true" />
        Where the time went
      </h3>

      {hasAnswer && (
        <dl className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1 font-mono text-2xs tabular-nums">
          <dt className="text-fg-muted">Time to first token</dt>
          <dd className="text-fg">{ttftKnown ? `${ttft} ms` : 'not measured'}</dd>
          {ttftKnown && preGenerate > 0 && (
            <>
              <dt className="text-fg-subtle" aria-hidden="true">
                =
              </dt>
              <dt className="text-fg-subtle">before the generator</dt>
              <dd className="text-fg-muted">{preGenerate} ms</dd>
              <dt className="text-fg-subtle" aria-hidden="true">
                +
              </dt>
              <dt className="text-fg-subtle">answer</dt>
              <dd className="text-fg-muted">{byKey.get('generate') ?? 0} ms</dd>
            </>
          )}
        </dl>
      )}

      <div
        className="mt-2 flex h-2.5 w-full overflow-hidden rounded-full bg-sidebar"
        role="img"
        aria-label={
          hasAnswer && ttftKnown
            ? `Total ${total} milliseconds. Time to first token ${ttft} milliseconds: ${preGenerate} before the generator, ${byKey.get('generate') ?? 0} generating the answer.`
            : `Total ${total} milliseconds across ${stages.length} stages.`
        }
      >
        {hasAnswer && (
          <div
            className="h-full bg-fg-muted"
            style={{ width: `${(waitMs / total) * 100}%` }}
          />
        )}
        {stages.slice(hasAnswer ? generateIndex : 0).map((key) => (
          <div
            key={key}
            className="h-full border-l border-main/40 bg-fg-strong first:border-l-0"
            style={{ width: `${((byKey.get(key) ?? 0) / total) * 100}%` }}
          />
        ))}
      </div>

      <ul className="mt-2 space-y-1.5">
        {stages.map((key) => {
          const ms = byKey.get(key) ?? 0
          const width = Math.max(1, Math.round((ms / total) * 100))
          return (
            <li key={key} className="flex items-baseline justify-between gap-2 text-xs">
              <span className="flex items-center gap-1.5 text-fg">
                {key === 'generate' && (
                  <ArrowRight size={12} strokeWidth={1.75} className="text-fg-subtle" aria-hidden="true" />
                )}
                {stageLabel(key)}
              </span>
              <span className="flex items-baseline gap-2">
                <span className="h-1.5 w-16 overflow-hidden rounded-full bg-raised">
                  <span className="block h-full rounded-full bg-fg-strong" style={{ width: `${width}%` }} />
                </span>
                <span className="w-14 text-right font-mono text-2xs tabular-nums text-fg-muted">
                  {ms} ms
                </span>
              </span>
            </li>
          )
        })}
      </ul>
      <p className="mt-2 font-mono text-2xs tabular-nums text-fg-muted">total {total} ms</p>
    </section>
  )
}