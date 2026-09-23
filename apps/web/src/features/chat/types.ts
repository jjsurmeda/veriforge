import type {
  AnswerDelta,
  Heartbeat,
  Metrics,
  Retrieval,
  RunCancelled,
  RunCompleted,
  RunFailed,
  RunStarted,
} from '../../generated/types.gen'

export type StreamEvent =
  | RunStarted
  | Retrieval
  | AnswerDelta
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
