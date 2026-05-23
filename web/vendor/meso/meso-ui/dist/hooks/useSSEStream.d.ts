import type { StreamState, StagePayload, MemorySnippet, MemorySavedPayload, CapabilitiesPayload, SoulPayload, SkillPayload, ToolCallPayload, ToolResultPayload, ResourceReadPayload, ResourceContentPayload, ArtifactState } from '../runtime';
export type { StreamState, StreamStatus, ArtifactState, ToolCallStatus, ToolCallState, ResourceReadStatus, ResourceReadState, SSEEvent, StageEvent, StagePayload, CapabilitiesEvent, CapabilitiesPayload, ToolSpec, SkillSpec, ResourceSpec, MCPServerSpec, MemoryEvent, MemorySnippet, MemorySavedEvent, MemorySavedPayload, SoulEvent, SoulPayload, SkillActiveEvent, SkillPayload, ThinkEvent, ThinkPayload, TextEvent, TextPayload, ArtifactEvent, CapabilityProvider, ToolRisk, ToolAnnotations, ToolCallEvent, ToolCallPayload, ToolResultEvent, ToolResultPayload, ResourceReadEvent, ResourceReadPayload, ResourceContentEvent, ResourceContentPayload, ResourceContentItem, DoneEvent, ErrorEvent, ExtensionEvent, ExtensionPayload, } from '../runtime';
export interface StreamOptions {
    method?: 'GET' | 'POST';
    headers?: Record<string, string>;
    body?: Record<string, unknown>;
}
/** Lifecycle callbacks fired after each matching SSE event is applied to state. */
export interface StreamCallbacks {
    onCapabilities?: (capabilities: CapabilitiesPayload) => void;
    onStageChange?: (stage: StagePayload) => void;
    onMemoryRecalled?: (snippets: MemorySnippet[]) => void;
    onMemorySaved?: (saved: MemorySavedPayload) => void;
    onSoulActivated?: (soul: SoulPayload) => void;
    onSkillActivated?: (skill: SkillPayload) => void;
    onToolCall?: (call: ToolCallPayload) => void;
    onToolResult?: (result: ToolResultPayload) => void;
    onResourceRead?: (read: ResourceReadPayload) => void;
    onResourceContent?: (content: ResourceContentPayload) => void;
    onArtifact?: (artifact: ArtifactState) => void;
    onError?: (message: string, code?: string) => void;
    onDone?: (finalState: StreamState) => void;
}
/**
 * React hook wrapping the Meso SSE runtime.
 * For fetch-free usage (custom transports, Node.js), import directly from
 * @meso/ui/runtime: { parseSSELine, applyEvent, createInitialStreamState }
 */
export declare function useSSEStream(url: string, callbacks?: StreamCallbacks): {
    state: StreamState;
    start: (options?: StreamOptions) => Promise<void>;
    abort: () => void;
    reset: () => void;
};
