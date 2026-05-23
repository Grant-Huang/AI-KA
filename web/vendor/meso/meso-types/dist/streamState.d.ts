import type { StagePayload, MemorySnippet, MemorySavedPayload, SoulPayload, SkillPayload, CapabilitiesPayload, ToolCallPayload, ToolResultPayload, ResourceReadPayload, ResourceContentPayload, ExtensionEvent } from './protocol';
export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';
export interface ArtifactState {
    id: string;
    lang: string;
    content: string;
    done: boolean;
}
export type ToolCallStatus = 'pending' | 'running' | 'awaiting_confirm' | 'done' | 'error';
export interface ToolCallState {
    call: ToolCallPayload;
    result?: ToolResultPayload;
    status: ToolCallStatus;
}
export type ResourceReadStatus = 'pending' | 'done' | 'error';
export interface ResourceReadState {
    read: ResourceReadPayload;
    content?: ResourceContentPayload;
    status: ResourceReadStatus;
}
export interface StreamState {
    status: StreamStatus;
    /** All capabilities available in this session — from the capabilities event. */
    availableCapabilities: CapabilitiesPayload | null;
    /** Active soul/persona; null until soul event received. */
    activeSoul: SoulPayload | null;
    /** Active skill/operational mode; null until skill_active event received. */
    activeSkill: SkillPayload | null;
    /** Pipeline stages in arrival order; deduped by name. */
    stages: StagePayload[];
    /** Memory snippets recalled before generation. */
    memorySnippets: MemorySnippet[];
    /** Memory entries persisted during this session (backend confirmations). */
    memorySaved: MemorySavedPayload[];
    /** Tool calls keyed by id for O(1) lookup and result correlation. */
    toolCalls: Record<string, ToolCallState>;
    /** Tool call ids in first-seen order — use for deterministic rendering. */
    toolCallOrder: string[];
    /** MCP resource reads keyed by id for O(1) lookup and content correlation. */
    resourceReads: Record<string, ResourceReadState>;
    /** Resource read ids in first-seen order — use for deterministic rendering. */
    resourceReadOrder: string[];
    thinkContent: string;
    thinkDone: boolean;
    textContent: string;
    /** Artifacts keyed by id for O(1) lookup during incremental updates. */
    artifacts: Record<string, ArtifactState>;
    /** Artifact ids in first-seen order — use for deterministic rendering. */
    artifactOrder: string[];
    /**
     * Extension events keyed by name for lookup (e.g. extensions["tool_progress"]).
     * For time-ordered rendering, use extensionLog instead.
     */
    extensions: Record<string, ExtensionEvent[]>;
    /** All extension events in arrival order — use when sequential rendering matters. */
    extensionLog: ExtensionEvent[];
    errorMessage: string | null;
}
export declare function createInitialStreamState(): StreamState;
