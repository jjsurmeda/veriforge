import type { StepCompleted, StepStarted } from '../../generated/types.gen'

export interface StepView {
  node: string
  label: string
  /** null while the step has started and not yet completed. */
  durationMs: number | null
}

/** The store appends both `step.started` and `step.completed`, so a finished
 *  step arrives as two events. The trace shows each step once, with its final
 *  state. A completion closes the latest still-open step of the same node, so
 *  a node that genuinely runs twice (a retry, a second hop) still shows twice. */
export function collapseSteps(steps: Array<StepStarted | StepCompleted>): StepView[] {
  const views: StepView[] = []
  for (const step of steps) {
    if (step.type === 'step.completed') {
      const open = [...views].reverse().find((view) => view.node === step.node && view.durationMs === null)
      if (open) open.durationMs = step.duration_ms
      else views.push({ node: step.node, label: step.label, durationMs: step.duration_ms })
    } else {
      views.push({ node: step.node, label: step.label, durationMs: null })
    }
  }
  return views
}
