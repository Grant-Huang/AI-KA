/**
 * Re-exports everything from @meso/types.
 * Implementation lives solely in @meso/types — do not duplicate here.
 *
 * Consumers who don't need React can import from @meso/types directly
 * (zero-dep, smaller bundle). This re-export exists so that
 * `@meso/ui/runtime` continues to work as a convenience path.
 */
export { PROTOCOL_VERSION, createInitialStreamState, applyEvent, parseSSELine, } from '@meso/types';
export type { ProtocolVersion, CapabilityProvider, SSEEvent, StageEvent, StagePayload, CapabilitiesEvent, CapabilitiesPayload, ToolSpec, SkillSpec, ResourceSpec, MCPServerSpec, MemoryEvent, MemorySnippet, MemoryPayload, MemorySavedEvent, MemorySavedPayload, SoulEvent, SoulPayload, SkillActiveEvent, SkillPayload, ThinkEvent, ThinkPayload, TextEvent, TextPayload, ArtifactEvent, ArtifactPayload, ToolRisk, ToolAnnotations, ToolCallEvent, ToolCallPayload, ToolResultEvent, ToolResultPayload, ResourceReadEvent, ResourceReadPayload, ResourceContentEvent, ResourceContentPayload, ResourceContentItem, DoneEvent, ErrorEvent, ErrorPayload, ExtensionEvent, ExtensionPayload, WorkflowNodeState, WorkflowNodePayload, WorkflowNodeEvent, StreamState, StreamStatus, ArtifactState, ToolCallStatus, ToolCallState, ResourceReadStatus, ResourceReadState, WorkflowNodeRecord, WorkflowRunState, } from '@meso/types';
