import type {
  Abstain,
  AnswerDelta,
  AnswerHold,
  AnswerRetract,
  Conflict,
  Decision,
  Heartbeat,
  Metrics,
  Plan,
  Retrieval,
  ReviewClaim,
  Revision,
  RunCancelled,
  RunCompleted,
  RunFailed,
  RunStarted,
  StepCompleted,
  StepStarted,
  Suggestions,
  ThinkingDelta,
} from '../../generated/types.gen'

export type StreamEvent =
  | RunStarted
  | StepStarted
  | StepCompleted
  | Decision
  | ThinkingDelta
  | Plan
  | Retrieval
  | AnswerDelta
  | Abstain
  | AnswerRetract
  | Conflict
  | ReviewClaim
  | AnswerHold
  | Revision
  | Suggestions
  | Metrics
  | Heartbeat
  | RunCompleted
  | RunCancelled
  | RunFailed

export type StreamEventType = StreamEvent['type']

export const TERMINAL_TYPES: ReadonlySet<StreamEventType> = new Set([
  'run.completed',
  'run.cancelled',
  'run.failed',
])
