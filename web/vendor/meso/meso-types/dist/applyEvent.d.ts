import type { SSEEvent } from './protocol';
import type { StreamState } from './streamState';
/**
 * Pure state machine reducer.
 * Apply one SSE event to the current StreamState and return the next state.
 * Does not mutate the input state.
 */
export declare function applyEvent(state: StreamState, event: SSEEvent): StreamState;
