/**
 * Meso SSE Streaming Protocol — v1.0
 *
 * Every event is wrapped in a standard envelope:
 *   data: {"type":"<event_type>","schema_version":"1.0","payload":{...}}\n\n
 *
 * This file is the single source of truth for event shapes.
 * useSSEStream, applyEvent, and all third-party backends must conform to it.
 */
export declare const PROTOCOL_VERSION: "1.0";
export type ProtocolVersion = typeof PROTOCOL_VERSION;
/** Standard envelope wrapping every SSE event. */
type Envelope<T extends string, P> = {
    type: T;
    schema_version: ProtocolVersion;
    payload: P;
};
/**
 * Who provides this capability.
 *   builtin — platform built-in (search_knowledge, save_memory, …)
 *   local   — app-defined function in the same process
 *   mcp     — served by an MCP (Model Context Protocol) server
 *   api     — external REST/gRPC endpoint
 */
export type CapabilityProvider = 'builtin' | 'local' | 'mcp' | 'api';
export interface StagePayload {
    name: string;
    state: 'active' | 'done' | 'error';
}
/** Pipeline stage progress (召回记忆, 检索知识, 生成回复, …). */
export type StageEvent = Envelope<'stage', StagePayload>;
export interface MemorySnippet {
    category: string;
    content: string;
}
export interface MemoryPayload {
    snippets: MemorySnippet[];
}
/** Memory recall results; replaces previous snippets when received. */
export type MemoryEvent = Envelope<'memory', MemoryPayload>;
export interface ThinkPayload {
    delta: string;
    /** true on the final think chunk — triggers auto-collapse in ThinkBlock. */
    done?: boolean;
}
/** Incremental reasoning text. */
export type ThinkEvent = Envelope<'think', ThinkPayload>;
export interface TextPayload {
    delta: string;
}
/** Incremental response text. */
export type TextEvent = Envelope<'text', TextPayload>;
export interface ArtifactPayload {
    /** Unique artifact identifier; multiple artifacts per response use distinct ids. */
    id: string;
    lang: string;
    delta: string;
    /** true on the final artifact chunk. */
    done?: boolean;
}
/** Incremental artifact content (code, HTML preview, Mermaid diagram, …). */
export type ArtifactEvent = Envelope<'artifact', ArtifactPayload>;
/** Stream ended successfully. Mutually exclusive with ErrorEvent. */
export type DoneEvent = Envelope<'done', Record<string, never>>;
export interface ErrorPayload {
    message: string;
    /** Optional machine-readable error code (e.g. "UPSTREAM_TIMEOUT"). */
    code?: string;
}
/** Unrecoverable error. Mutually exclusive with DoneEvent. */
export type ErrorEvent = Envelope<'error', ErrorPayload>;
export type ToolRisk = 'safe' | 'write' | 'destructive';
export interface ToolSpec {
    name: string;
    description?: string;
    provider: CapabilityProvider;
    server?: string;
    risk?: ToolRisk;
    input_schema?: Record<string, unknown>;
}
export interface SkillSpec {
    id: string;
    name: string;
    description?: string;
    provider?: CapabilityProvider;
    server?: string;
    focus_points?: Array<{
        id: string;
        name: string;
    }>;
}
export interface ResourceSpec {
    uri: string;
    name?: string;
    description?: string;
    server?: string;
    mime_type?: string;
}
export interface MCPServerSpec {
    name: string;
    version?: string;
    capabilities: Array<'tools' | 'resources' | 'prompts' | 'sampling'>;
}
export interface CapabilitiesPayload {
    tools?: ToolSpec[];
    skills?: SkillSpec[];
    resources?: ResourceSpec[];
    mcp_servers?: MCPServerSpec[];
}
export type CapabilitiesEvent = Envelope<'capabilities', CapabilitiesPayload>;
export interface SoulPayload {
    id: string;
    name: string;
    version: string;
    avatar?: string;
    traits?: string[];
}
export type SoulEvent = Envelope<'soul', SoulPayload>;
export interface SkillPayload {
    id: string;
    name: string;
    version?: string;
    provider?: CapabilityProvider;
    server?: string;
    focus?: string[];
    description?: string;
}
export type SkillActiveEvent = Envelope<'skill_active', SkillPayload>;
export interface MemorySavedPayload {
    id: string;
    category: string;
    preview: string;
}
export type MemorySavedEvent = Envelope<'memory_saved', MemorySavedPayload>;
export interface ToolAnnotations {
    idempotent?: boolean;
    open_world?: boolean;
}
export interface ToolCallPayload {
    id: string;
    name: string;
    args: Record<string, unknown>;
    risk?: ToolRisk;
    provider?: CapabilityProvider;
    server?: string;
    annotations?: ToolAnnotations;
}
export type ToolCallEvent = Envelope<'tool_call', ToolCallPayload>;
export interface ToolResultPayload {
    tool_call_id: string;
    output: string;
    error?: string;
    duration_ms?: number;
}
export type ToolResultEvent = Envelope<'tool_result', ToolResultPayload>;
export interface ResourceReadPayload {
    id: string;
    uri: string;
    name?: string;
    server?: string;
}
export type ResourceReadEvent = Envelope<'resource_read', ResourceReadPayload>;
export interface ResourceContentItem {
    type: 'text' | 'image' | 'blob';
    text?: string;
    data?: string;
    mime_type?: string;
}
export interface ResourceContentPayload {
    resource_read_id: string;
    contents: ResourceContentItem[];
    error?: string;
    duration_ms?: number;
}
export type ResourceContentEvent = Envelope<'resource_content', ResourceContentPayload>;
export type WorkflowNodeState = 'active' | 'done' | 'error' | 'skipped';
export interface WorkflowNodePayload {
    run_id: string;
    node_id: string;
    parent_id?: string | null;
    name: string;
    state: WorkflowNodeState;
    started_at?: number;
    duration_ms?: number;
    metadata?: Record<string, unknown>;
}
export type WorkflowNodeEvent = Envelope<'workflow_node', WorkflowNodePayload>;
export interface ExtensionPayload {
    name: string;
    version?: string;
    data: unknown;
}
export type ExtensionEvent = Envelope<'extension', ExtensionPayload>;
export type SSEEvent = StageEvent | CapabilitiesEvent | MemoryEvent | MemorySavedEvent | SoulEvent | SkillActiveEvent | ThinkEvent | TextEvent | ArtifactEvent | ToolCallEvent | ToolResultEvent | ResourceReadEvent | ResourceContentEvent | WorkflowNodeEvent | DoneEvent | ErrorEvent | ExtensionEvent;
export {};
