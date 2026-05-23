import type { SSEEvent } from './protocol';
/**
 * Parse a single SSE data line into an SSEEvent.
 *
 * Returns:
 *   SSEEvent  — valid protocol 1.0 event
 *   null      — empty line, comment (": …"), non-data line, invalid JSON,
 *               or missing required fields (skip silently)
 *
 * Special cases:
 *   "data: [DONE]"  → normalized to DoneEvent (same as {"type":"done",...})
 *   Missing schema_version → assumed "1.0" for transition-period tolerance
 */
export declare function parseSSELine(line: string): SSEEvent | null;
