const s = "1.0";
function t() {
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
    extensions: {},
    extensionLog: [],
    errorMessage: null
  };
}
function i(r, o) {
  switch (o.type) {
    case "capabilities":
      return { ...r, availableCapabilities: o.payload };
    case "stage": {
      const { name: a, state: e } = o.payload;
      return {
        ...r,
        stages: [
          ...r.stages.filter((l) => l.name !== a),
          { name: a, state: e }
        ]
      };
    }
    case "memory":
      return { ...r, memorySnippets: o.payload.snippets };
    case "memory_saved":
      return { ...r, memorySaved: [...r.memorySaved, o.payload] };
    case "soul":
      return { ...r, activeSoul: o.payload };
    case "skill_active":
      return { ...r, activeSkill: o.payload };
    case "tool_call": {
      const { id: a } = o.payload;
      return {
        ...r,
        toolCallOrder: r.toolCallOrder.includes(a) ? r.toolCallOrder : [...r.toolCallOrder, a],
        toolCalls: {
          ...r.toolCalls,
          [a]: { call: o.payload, status: "pending" }
        }
      };
    }
    case "tool_result": {
      const { tool_call_id: a } = o.payload, e = r.toolCalls[a], l = o.payload.error ? "error" : "done";
      return {
        ...r,
        toolCalls: {
          ...r.toolCalls,
          [a]: {
            call: (e == null ? void 0 : e.call) ?? { id: a, name: "(unknown)", args: {} },
            result: o.payload,
            status: l
          }
        }
      };
    }
    case "resource_read": {
      const { id: a } = o.payload;
      return {
        ...r,
        resourceReadOrder: r.resourceReadOrder.includes(a) ? r.resourceReadOrder : [...r.resourceReadOrder, a],
        resourceReads: {
          ...r.resourceReads,
          [a]: { read: o.payload, status: "pending" }
        }
      };
    }
    case "resource_content": {
      const { resource_read_id: a } = o.payload, e = r.resourceReads[a], l = o.payload.error ? "error" : "done";
      return {
        ...r,
        resourceReads: {
          ...r.resourceReads,
          [a]: {
            read: (e == null ? void 0 : e.read) ?? { id: a, uri: "(unknown)" },
            content: o.payload,
            status: l
          }
        }
      };
    }
    case "think":
      return {
        ...r,
        thinkContent: r.thinkContent + o.payload.delta,
        thinkDone: o.payload.done ?? !1
      };
    case "text":
      return { ...r, textContent: r.textContent + o.payload.delta };
    case "artifact": {
      const { id: a, lang: e, delta: l, done: d } = o.payload, n = r.artifacts[a], c = r.artifactOrder.includes(a) ? r.artifactOrder : [...r.artifactOrder, a];
      return {
        ...r,
        artifactOrder: c,
        artifacts: {
          ...r.artifacts,
          [a]: {
            id: a,
            lang: e,
            content: ((n == null ? void 0 : n.content) ?? "") + l,
            done: d ?? !1
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
        errorMessage: o.payload.message
      };
    case "extension": {
      const { name: a } = o.payload;
      return {
        ...r,
        extensions: {
          ...r.extensions,
          [a]: [...r.extensions[a] ?? [], o]
        },
        extensionLog: [...r.extensionLog, o]
      };
    }
    default:
      return r;
  }
}
function u(r) {
  if (!r.startsWith("data: ")) return null;
  const o = r.slice(6).trim();
  if (o === "[DONE]")
    return { type: "done", schema_version: s, payload: {} };
  let a;
  try {
    a = JSON.parse(o);
  } catch {
    return null;
  }
  if (!a || typeof a != "object" || Array.isArray(a)) return null;
  const e = a;
  return typeof e.type != "string" || !e.payload || typeof e.payload != "object" || Array.isArray(e.payload) ? null : (e.schema_version || (e.schema_version = s), e);
}
export {
  s as PROTOCOL_VERSION,
  i as applyEvent,
  t as createInitialStreamState,
  u as parseSSELine
};
