import type {
  Abstain,
  AnswerDelta,
  Conflict,
  Decision,
  Heartbeat,
  Metrics,
  Retrieval,
  RunCancelled,
  RunCompleted,
  RunFailed,
  RunStarted,
  StepCompleted,
  StepStarted,
  ThinkingDelta,
} from '../../generated/types.gen'

export type StreamEvent =
  | RunStarted
  | StepStarted
  | StepCompleted
  | Decision
  | ThinkingDelta
  | Retrieval
  | AnswerDelta
  | Abstain
  | Conflict
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
