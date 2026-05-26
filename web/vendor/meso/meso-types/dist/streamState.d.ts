import type { StagePayload, MemorySnippet, MemorySavedPayload, SoulPayload, SkillPayload, CapabilitiesPayload, ToolCallPayload, ToolResultPayload, ResourceReadPayload, ResourceContentPayload, ExtensionEvent, WorkflowNodeState } from './protocol';
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
export interface WorkflowNodeRecord {
    node_id: string;
    run_id: string;
    parent_id?: string | null;
    name: string;
    state: WorkflowNodeState;
    started_at?: number;
    duration_ms?: number;
    metadata?: Record<string, unknown>;
}
export interface WorkflowRunState {
    run_id: string;
    nodes: Record<string, WorkflowNodeRecord>;
    nodeOrder: string[];
}
export interface StreamState {
    status: StreamStatus;
    availableCapabilities: CapabilitiesPayload | null;
    activeSoul: SoulPayload | null;
    activeSkill: SkillPayload | null;
    stages: StagePayload[];
    memorySnippets: MemorySnippet[];
    memorySaved: MemorySavedPayload[];
    toolCalls: Record<string, ToolCallState>;
    toolCallOrder: string[];
    resourceReads: Record<string, ResourceReadState>;
    resourceReadOrder: string[];
    thinkContent: string;
    thinkDone: boolean;
    textContent: string;
    artifacts: Record<string, ArtifactState>;
    artifactOrder: string[];
    workflowRuns: Record<string, WorkflowRunState>;
    workflowRunOrder: string[];
    extensions: Record<string, ExtensionEvent[]>;
    extensionLog: ExtensionEvent[];
    errorMessage: string | null;
}
export declare function createInitialStreamState(): StreamState;
