const n = "1.0";
function i() {
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
function c(e, t) {
  switch (t.type) {
    case "capabilities":
      return { ...e, availableCapabilities: t.payload };
    case "stage": {
      const { name: a, state: s } = t.payload;
      return {
        ...e,
        stages: [
          ...e.stages.filter((r) => r.name !== a),
          { name: a, state: s }
        ]
      };
    }
    case "memory":
      return { ...e, memorySnippets: t.payload.snippets };
    case "memory_saved":
      return { ...e, memorySaved: [...e.memorySaved, t.payload] };
    case "soul":
      return { ...e, activeSoul: t.payload };
    case "skill_active":
      return { ...e, activeSkill: t.payload };
    case "tool_call": {
      const { id: a } = t.payload;
      return {
        ...e,
        toolCallOrder: e.toolCallOrder.includes(a) ? e.toolCallOrder : [...e.toolCallOrder, a],
        toolCalls: {
          ...e.toolCalls,
          [a]: { call: t.payload, status: "pending" }
        }
      };
    }
    case "tool_result": {
      const { tool_call_id: a } = t.payload, s = e.toolCalls[a], r = t.payload.error ? "error" : "done";
      return {
        ...e,
        toolCalls: {
          ...e.toolCalls,
          [a]: {
            call: (s == null ? void 0 : s.call) ?? { id: a, name: "(unknown)", args: {} },
            result: t.payload,
            status: r
          }
        }
      };
    }
    case "resource_read": {
      const { id: a } = t.payload;
      return {
        ...e,
        resourceReadOrder: e.resourceReadOrder.includes(a) ? e.resourceReadOrder : [...e.resourceReadOrder, a],
        resourceReads: {
          ...e.resourceReads,
          [a]: { read: t.payload, status: "pending" }
        }
      };
    }
    case "resource_content": {
      const { resource_read_id: a } = t.payload, s = e.resourceReads[a], r = t.payload.error ? "error" : "done";
      return {
        ...e,
        resourceReads: {
          ...e.resourceReads,
          [a]: {
            read: (s == null ? void 0 : s.read) ?? { id: a, uri: "(unknown)" },
            content: t.payload,
            status: r
          }
        }
      };
    }
    case "think":
      return {
        ...e,
        thinkContent: e.thinkContent + t.payload.delta,
        thinkDone: t.payload.done ?? !1
      };
    case "text":
      return { ...e, textContent: e.textContent + t.payload.delta };
    case "artifact": {
      const { id: a, lang: s, delta: r, done: o } = t.payload, l = e.artifacts[a], d = e.artifactOrder.includes(a) ? e.artifactOrder : [...e.artifactOrder, a];
      return {
        ...e,
        artifactOrder: d,
        artifacts: {
          ...e.artifacts,
          [a]: {
            id: a,
            lang: s,
            content: ((l == null ? void 0 : l.content) ?? "") + r,
            done: o ?? !1
          }
        }
      };
    }
    case "done":
      return { ...e, status: "done" };
    case "error":
      return {
        ...e,
        status: "error",
        errorMessage: t.payload.message
      };
    case "extension": {
      const { name: a } = t.payload;
      return {
        ...e,
        extensions: {
          ...e.extensions,
          [a]: [...e.extensions[a] ?? [], t]
        },
        extensionLog: [...e.extensionLog, t]
      };
    }
    default:
      return e;
  }
}
function u(e) {
  if (!e.startsWith("data: ")) return null;
  const t = e.slice(6).trim();
  if (t === "[DONE]")
    return { type: "done", schema_version: n, payload: {} };
  let a;
  try {
    a = JSON.parse(t);
  } catch {
    return null;
  }
  if (!a || typeof a != "object" || Array.isArray(a)) return null;
  const s = a;
  return typeof s.type != "string" || !s.payload || typeof s.payload != "object" || Array.isArray(s.payload) ? null : (s.schema_version || (s.schema_version = n), s);
}
export {
  n as PROTOCOL_VERSION,
  c as applyEvent,
  i as createInitialStreamState,
  u as parseSSELine
};
