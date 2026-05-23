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
    /**
     * Content language/type. Well-known values:
     *   "html preview" | "mermaid" | "python" | "typescript" | …
     */
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
    /** MCP server name when provider = "mcp". */
    server?: string;
    risk?: ToolRisk;
    /** JSON Schema for the tool's input parameters. */
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
    /** MCP resource URI (e.g. "file:///path/to/doc" or "db://table/id"). */
    uri: string;
    name?: string;
    description?: string;
    /** MCP server that exposes this resource. */
    server?: string;
    mime_type?: string;
}
export interface MCPServerSpec {
    name: string;
    version?: string;
    /** Which MCP capability groups this server exposes. */
    capabilities: Array<'tools' | 'resources' | 'prompts' | 'sampling'>;
}
export interface CapabilitiesPayload {
    tools?: ToolSpec[];
    skills?: SkillSpec[];
    resources?: ResourceSpec[];
    mcp_servers?: MCPServerSpec[];
}
/**
 * Capability discovery — sent once at stream start.
 * Frontend uses this to populate skill selectors, tool toggles, and MCP panels.
 * Backend sends only what is relevant to the current session/app.
 */
export type CapabilitiesEvent = Envelope<'capabilities', CapabilitiesPayload>;
export interface SoulPayload {
    /** Stable identifier for this soul definition. */
    id: string;
    /** Display name shown in UI. */
    name: string;
    /** Semver of the soul definition — bumped when personality changes. */
    version: string;
    /** Optional avatar URL or data URI. */
    avatar?: string;
    /** Optional trait tags for UI display (e.g. ["严谨", "好奇"]). */
    traits?: string[];
}
/** Active soul/persona notification — sent once at stream start. */
export type SoulEvent = Envelope<'soul', SoulPayload>;
export interface SkillPayload {
    id: string;
    name: string;
    version?: string;
    provider?: CapabilityProvider;
    /** MCP server name when provider = "mcp" (MCP prompt → Meso skill). */
    server?: string;
    /** Active focus_point ids selected for this invocation. */
    focus?: string[];
    description?: string;
}
/**
 * Skill activation — emitted when backend selects or switches operational mode.
 * Maps MCP prompts to the same signal: backends translate get_prompt results
 * into skill_active before injecting the prompt content into the system prompt.
 */
export type SkillActiveEvent = Envelope<'skill_active', SkillPayload>;
export interface MemorySavedPayload {
    /** Unique id of the saved memory entry. */
    id: string;
    category: string;
    /** Short excerpt for toast display (≤ 80 chars). */
    preview: string;
}
/** Backend confirmation that a memory was persisted during this session. */
export type MemorySavedEvent = Envelope<'memory_saved', MemorySavedPayload>;
/** MCP tool annotations mapped to platform-standard fields. */
export interface ToolAnnotations {
    /** Tool result is safe to retry (MCP: idempotentHint). */
    idempotent?: boolean;
    /** Tool may make external network calls (MCP: openWorldHint). */
    open_world?: boolean;
}
export interface ToolCallPayload {
    /** Unique id scoping this invocation within the response. */
    id: string;
    name: string;
    args: Record<string, unknown>;
    /**
     * Risk level hint for UI rendering and confirm gate.
     * Omit or use "safe" for read-only tools.
     * Maps from MCP annotations: readOnlyHint → safe, destructiveHint → destructive.
     */
    risk?: ToolRisk;
    /** Who provides this tool. Omit for platform built-ins. */
    provider?: CapabilityProvider;
    /** MCP server name when provider = "mcp". */
    server?: string;
    /** Optional MCP-originated behaviour hints for UI rendering. */
    annotations?: ToolAnnotations;
}
/** LLM decided to call a tool — emitted before execution starts. */
export type ToolCallEvent = Envelope<'tool_call', ToolCallPayload>;
export interface ToolResultPayload {
    /** Matches the id from the corresponding tool_call event. */
    tool_call_id: string;
    /** Serialised output (stringified JSON, plain text, etc.). */
    output: string;
    /** Present only on failure. */
    error?: string;
    duration_ms?: number;
}
/** Tool execution completed (success or error). */
export type ToolResultEvent = Envelope<'tool_result', ToolResultPayload>;
export interface ResourceReadPayload {
    /** Unique id scoping this read within the response (for correlation). */
    id: string;
    /** MCP resource URI (e.g. "file:///path/to/doc"). */
    uri: string;
    name?: string;
    /** MCP server that serves this resource. */
    server?: string;
}
/** LLM or backend requested a resource read — emitted before content arrives. */
export type ResourceReadEvent = Envelope<'resource_read', ResourceReadPayload>;
export interface ResourceContentItem {
    type: 'text' | 'image' | 'blob';
    /** Present when type = "text". */
    text?: string;
    /** Present when type = "image" | "blob". Base64-encoded. */
    data?: string;
    mime_type?: string;
}
export interface ResourceContentPayload {
    /** Matches the id from the corresponding resource_read event. */
    resource_read_id: string;
    contents: ResourceContentItem[];
    /** Present only on failure. */
    error?: string;
    duration_ms?: number;
}
/** Resource content arrived (or failed). */
export type ResourceContentEvent = Envelope<'resource_content', ResourceContentPayload>;
export interface ExtensionPayload {
    /** Identifies the extension type (e.g. "tool_progress", "confirm_gate"). */
    name: string;
    /** Optional semver for the extension schema itself. */
    version?: string;
    data: unknown;
}
/** Third-party extension event — consumed via MessageList's renderExtension prop. */
export type ExtensionEvent = Envelope<'extension', ExtensionPayload>;
export type SSEEvent = StageEvent | CapabilitiesEvent | MemoryEvent | MemorySavedEvent | SoulEvent | SkillActiveEvent | ThinkEvent | TextEvent | ArtifactEvent | ToolCallEvent | ToolResultEvent | ResourceReadEvent | ResourceContentEvent | DoneEvent | ErrorEvent | ExtensionEvent;
export {};
