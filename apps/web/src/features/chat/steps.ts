import type { StreamEvent } from './types'

type StepStatus = 'active' | 'done' | 'failed' | 'warning'

export interface WorkingStep {
  id: string
  label: string
  detail?: string
  status: StepStatus
}

export function describeStep(event: StreamEvent): WorkingStep {
  switch (event.type) {
    case 'run.started':
      return { id: `${event.seq ?? 0}-run`, label: 'Starting run', status: 'active' }
    case 'plan':
      return {
        id: `${event.seq ?? 0}-plan`,
        label: 'Planning',
        detail: event.sub_questions.map((question) => question.question).join(' · '),
        status: 'active',
      }
    case 'step.started':
      return { id: `${event.seq ?? 0}-${event.node}`, label: event.label, status: 'active' }
    case 'step.completed':
      return { id: `${event.seq ?? 0}-${event.node}`, label: event.label, status: 'done' }
    case 'retrieval':
      return {
        id: `${event.seq ?? 0}-retrieval`,
        label: 'Searching your sources',
        detail: `${event.chunks?.length ?? 0} passages found`,
        status: 'done',
      }
    case 'decision':
      return {
        id: `${event.seq ?? 0}-${event.name}`,
        label: `Routing: ${event.name}`,
        detail: String(event.value),
        status: 'done',
      }
    case 'thinking.delta':
      return { id: `${event.seq ?? 0}-thinking`, label: 'Thinking', detail: event.text, status: 'active' }
    case 'answer.hold':
      return { id: `${event.seq ?? 0}-hold`, label: 'Reviewing the answer', status: 'active' }
    case 'review.claim':
      return { id: `${event.seq ?? 0}-review`, label: 'Reviewing claims', status: 'active' }
    case 'revision':
      return { id: `${event.seq ?? 0}-revision`, label: 'Revising the answer', status: 'active' }
    case 'answer.delta':
      return { id: `${event.seq ?? 0}-answer`, label: 'Writing the answer', status: 'active' }
    case 'conflict':
      return { id: `${event.seq ?? 0}-conflict`, label: 'Reviewing conflicting evidence', status: 'warning' }
    case 'abstain':
      return { id: `${event.seq ?? 0}-abstain`, label: 'Checking the evidence', status: 'warning' }
    case 'answer.retract':
      // A streamed answer struck by IsUse; the text the client renders is
      // replaced wholesale by the decline (ADR-006 item 4).
      return { id: `${event.seq ?? 0}-retract`, label: 'Withdrawing the answer', status: 'warning' }
    case 'suggestions':
      return { id: `${event.seq ?? 0}-suggestions`, label: 'Finding follow-ups', status: 'done' }
    case 'metrics':
      return { id: `${event.seq ?? 0}-metrics`, label: 'Finalising run details', status: 'done' }
    case 'run.completed':
      return { id: `${event.seq ?? 0}-complete`, label: 'Complete', status: 'done' }
    case 'run.cancelled':
      return { id: `${event.seq ?? 0}-cancelled`, label: 'Cancelled', status: 'failed' }
    case 'run.failed':
      return { id: `${event.seq ?? 0}-failed`, label: 'Run failed', status: 'failed' }
    case 'heartbeat':
      return { id: `${event.seq ?? 0}-heartbeat`, label: 'Still working', status: 'active' }
    default:
      return { id: 'unknown', label: 'Working', status: 'active' }
  }
}
