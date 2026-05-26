import type { StagePayload } from './protocol';
/**
 * UI Stage shape — mirrors StageTimeline component props.
 * Defined here so the adapter can be used without importing @meso/ui.
 */
export interface Stage {
    id: string;
    label: string;
    status: 'pending' | 'active' | 'done' | 'error';
}
/**
 * Convert a protocol StagePayload into a Stage ready for <StageTimeline>.
 *
 * Field mapping:
 *   payload.name  → stage.label
 *   payload.state → stage.status  (protocol 'error' maps to UI 'error')
 *
 * @param payload  The StagePayload from the SSE event
 * @param id       Stable identity (use payload.name or a loop index)
 */
export declare function stagePayloadToStage(payload: StagePayload, id: string): Stage;
