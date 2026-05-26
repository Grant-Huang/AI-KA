const d = "1.0";
function f() {
  return {
    status: "idle",
    availableCapabilities: null,
    activeSoul: null,
    activeSkill: null,
    stages: [],
    memorySnippets: [],
    memorySaved: [],
    toolCalls: {},
    toolCallOrder: [],
    resourceReads: {},
    resourceReadOrder: [],
    thinkContent: "",
    thinkDone: !1,
    textContent: "",
    artifacts: {},
    artifactOrder: [],
    workflowRuns: {},
    workflowRunOrder: [],
    extensions: {},
    extensionLog: [],
    errorMessage: null
  };
}
function m(r, e) {
  switch (e.type) {
    case "capabilities":
      return { ...r, availableCapabilities: e.payload };
    case "stage": {
      const { name: o, state: a } = e.payload;
      return {
        ...r,
        stages: [
          ...r.stages.filter((n) => n.name !== o),
          { name: o, state: a }
        ]
      };
    }
    case "memory":
      return { ...r, memorySnippets: e.payload.snippets };
    case "memory_saved":
      return { ...r, memorySaved: [...r.memorySaved, e.payload] };
    case "soul":
      return { ...r, activeSoul: e.payload };
    case "skill_active":
      return { ...r, activeSkill: e.payload };
    case "tool_call": {
      const { id: o } = e.payload;
      return {
        ...r,
        toolCallOrder: r.toolCallOrder.includes(o) ? r.toolCallOrder : [...r.toolCallOrder, o],
        toolCalls: {
          ...r.toolCalls,
          [o]: { call: e.payload, status: "pending" }
        }
      };
    }
    case "tool_result": {
      const { tool_call_id: o } = e.payload, a = r.toolCalls[o], n = e.payload.error ? "error" : "done";
      return {
        ...r,
        toolCalls: {
          ...r.toolCalls,
          [o]: {
            call: (a == null ? void 0 : a.call) ?? { id: o, name: "(unknown)", args: {} },
            result: e.payload,
            status: n
          }
        }
      };
    }
    case "resource_read": {
      const { id: o } = e.payload;
      return {
        ...r,
        resourceReadOrder: r.resourceReadOrder.includes(o) ? r.resourceReadOrder : [...r.resourceReadOrder, o],
        resourceReads: {
          ...r.resourceReads,
          [o]: { read: e.payload, status: "pending" }
        }
      };
    }
    case "resource_content": {
      const { resource_read_id: o } = e.payload, a = r.resourceReads[o], n = e.payload.error ? "error" : "done";
      return {
        ...r,
        resourceReads: {
          ...r.resourceReads,
          [o]: {
            read: (a == null ? void 0 : a.read) ?? { id: o, uri: "(unknown)" },
            content: e.payload,
            status: n
          }
        }
      };
    }
    case "think":
      return {
        ...r,
        thinkContent: r.thinkContent + e.payload.delta,
        thinkDone: e.payload.done ?? !1
      };
    case "text":
      return { ...r, textContent: r.textContent + e.payload.delta };
    case "artifact": {
      const { id: o, lang: a, delta: n, done: t } = e.payload, l = r.artifacts[o], c = r.artifactOrder.includes(o) ? r.artifactOrder : [...r.artifactOrder, o];
      return {
        ...r,
        artifactOrder: c,
        artifacts: {
          ...r.artifacts,
          [o]: {
            id: o,
            lang: a,
            content: ((l == null ? void 0 : l.content) ?? "") + n,
            done: t ?? !1
          }
        }
      };
    }
    case "workflow_node": {
      const { run_id: o, node_id: a, parent_id: n, name: t, state: l, started_at: c, duration_ms: i, metadata: u } = e.payload, s = r.workflowRuns[o] ?? { nodes: {}, nodeOrder: [] }, p = s.nodeOrder.includes(a) ? s.nodeOrder : [...s.nodeOrder, a];
      return {
        ...r,
        workflowRunOrder: r.workflowRunOrder.includes(o) ? r.workflowRunOrder : [...r.workflowRunOrder, o],
        workflowRuns: {
          ...r.workflowRuns,
          [o]: {
            run_id: o,
            nodes: {
              ...s.nodes,
              [a]: { node_id: a, run_id: o, parent_id: n, name: t, state: l, started_at: c, duration_ms: i, metadata: u }
            },
            nodeOrder: p
          }
        }
      };
    }
    case "done":
      return { ...r, status: "done" };
    case "error":
      return {
        ...r,
        status: "error",
        errorMessage: e.payload.message
      };
    case "extension": {
      const { name: o } = e.payload;
      return {
        ...r,
        extensions: {
          ...r.extensions,
          [o]: [...r.extensions[o] ?? [], e]
        },
        extensionLog: [...r.extensionLog, e]
      };
    }
    default:
      return r;
  }
}
function O(r) {
  if (!r.startsWith("data: ")) return null;
  const e = r.slice(6).trim();
  if (e === "[DONE]")
    return { type: "done", schema_version: d, payload: {} };
  let o;
  try {
    o = JSON.parse(e);
  } catch {
    return null;
  }
  if (!o || typeof o != "object" || Array.isArray(o)) return null;
  const a = o;
  return typeof a.type != "string" || !a.payload || typeof a.payload != "object" || Array.isArray(a.payload) ? null : (a.schema_version || (a.schema_version = d), a);
}
function y(r) {
  const [e] = d.split(".").map(Number), [o] = (r.schema_version ?? "").split(".").map(Number);
  return o === e;
}
function w(r) {
  if (!y(r))
    throw new Error(
      `Meso protocol version mismatch: runtime expects ${d}, received ${r.schema_version}. Upgrade @meso/types or your backend.`
    );
}
function R(r, e) {
  return {
    id: e,
    label: r.name,
    status: r.state
  };
}
export {
  d as PROTOCOL_VERSION,
  m as applyEvent,
  w as assertCompatibleVersion,
  f as createInitialStreamState,
  y as isCompatibleVersion,
  O as parseSSELine,
  R as stagePayloadToStage
};
