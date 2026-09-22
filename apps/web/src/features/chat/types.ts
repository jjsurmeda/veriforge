import type {
  AnswerDelta,
  Heartbeat,
  RunCancelled,
  RunCompleted,
  RunFailed,
  RunStarted,
} from '../../generated/types.gen'

export type StreamEvent =
  | RunStarted
  | AnswerDelta
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
