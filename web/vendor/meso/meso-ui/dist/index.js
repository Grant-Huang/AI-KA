import { jsxs as o, jsx as e, Fragment as M } from "react/jsx-runtime";
import Z, { useState as w, useRef as $, useCallback as T, useEffect as O } from "react";
import { createInitialStreamState as V, parseSSELine as se, applyEvent as oe } from "./runtime.js";
import { PROTOCOL_VERSION as He } from "./runtime.js";
const q = 0.4, Q = 0.8, te = 0.6;
function ne(r, a) {
  if (!r) return a;
  try {
    const t = parseFloat(localStorage.getItem(r) ?? "");
    if (!isNaN(t) && t >= q && t <= Q) return t;
  } catch {
  }
  return a;
}
function X(r, a) {
  if (r)
    try {
      localStorage.setItem(r, String(a));
    } catch {
    }
}
function Re({
  navItems: r = [],
  sidebarFooter: a,
  sessionColumn: t,
  sessionColumnVisible: s = !0,
  children: n,
  defaultCollapsed: c = !1,
  appName: u = "Meso",
  mainHeader: m,
  artifactContent: h,
  splitMode: l = !1,
  onSplitModeChange: f,
  defaultSplitRatio: b = te,
  onSplitRatioChange: k,
  splitRatioStorageKey: p
}) {
  const [L, i] = w(c), [_, x] = w(
    () => ne(p, b)
  ), S = $(!1), C = $(null), A = T((v) => {
    v.currentTarget.setPointerCapture(v.pointerId), S.current = !0;
  }, []), R = T((v) => {
    if (!S.current || !C.current) return;
    const g = C.current.getBoundingClientRect(), W = (v.clientX - g.left) / g.width, E = Math.min(Q, Math.max(q, W));
    x(E);
  }, []), B = T((v) => {
    S.current && (S.current = !1, v.currentTarget.releasePointerCapture(v.pointerId), x((g) => (X(p, g), k == null || k(g), g)));
  }, [p, k]);
  O(() => {
    X(p, _);
  }, [p]);
  const y = l && !!h;
  return /* @__PURE__ */ o("div", { className: "meso-layout", children: [
    /* @__PURE__ */ o("aside", { className: `meso-sidebar${L ? " meso-sidebar--collapsed" : ""}`, children: [
      /* @__PURE__ */ o("div", { className: "meso-sidebar__header", children: [
        /* @__PURE__ */ e("div", { className: "meso-sidebar__logo", children: u[0] }),
        /* @__PURE__ */ e("span", { className: "meso-sidebar__title", children: u }),
        /* @__PURE__ */ e(
          "button",
          {
            className: "meso-sidebar__toggle",
            onClick: () => i(!L),
            "aria-label": L ? "展开侧栏" : "收起侧栏",
            children: /* @__PURE__ */ o("svg", { width: "16", height: "16", viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", children: [
              /* @__PURE__ */ e("line", { x1: "2", y1: "4", x2: "14", y2: "4" }),
              /* @__PURE__ */ e("line", { x1: "2", y1: "8", x2: "14", y2: "8" }),
              /* @__PURE__ */ e("line", { x1: "2", y1: "12", x2: "14", y2: "12" })
            ] })
          }
        )
      ] }),
      /* @__PURE__ */ e("nav", { className: "meso-sidebar__nav", children: r.map((v) => /* @__PURE__ */ o(
        "div",
        {
          className: `meso-sidebar__nav-item${v.active ? " meso-sidebar__nav-item--active" : ""}`,
          onClick: v.onClick,
          title: v.label,
          children: [
            /* @__PURE__ */ e("span", { className: "meso-sidebar__nav-icon", children: v.icon }),
            /* @__PURE__ */ e("span", { className: "meso-sidebar__nav-label", children: v.label })
          ]
        },
        v.id
      )) }),
      a && /* @__PURE__ */ e("div", { className: "meso-sidebar__footer", children: a })
    ] }),
    t !== void 0 && /* @__PURE__ */ e("div", { className: `meso-session-col${s ? "" : " meso-session-col--hidden"}`, children: t }),
    /* @__PURE__ */ o("main", { className: "meso-main", ref: C, children: [
      m && /* @__PURE__ */ o("div", { className: "meso-main__header", children: [
        m,
        h && /* @__PURE__ */ e(
          "button",
          {
            className: "meso-main__artifact-toggle",
            onClick: () => f == null ? void 0 : f(!l),
            "aria-label": l ? "收起预览" : "展开预览",
            title: l ? "收起预览" : "展开预览",
            children: /* @__PURE__ */ e("svg", { width: "16", height: "16", viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round", children: l ? (
              // collapse: chevron right
              /* @__PURE__ */ e("polyline", { points: "6,3 11,8 6,13" })
            ) : (
              // expand: split columns icon
              /* @__PURE__ */ o(M, { children: [
                /* @__PURE__ */ e("rect", { x: "1", y: "2", width: "14", height: "12", rx: "1.5" }),
                /* @__PURE__ */ e("line", { x1: "8", y1: "2", x2: "8", y2: "14" })
              ] })
            ) })
          }
        )
      ] }),
      /* @__PURE__ */ e("div", { className: "meso-main__content", children: y ? /* @__PURE__ */ o(M, { children: [
        /* @__PURE__ */ e(
          "div",
          {
            className: "meso-main__chat",
            style: { width: `${_ * 100}%` },
            children: n
          }
        ),
        /* @__PURE__ */ e(
          "div",
          {
            className: "meso-split-divider",
            role: "separator",
            "aria-label": "拖动调整宽度",
            onPointerDown: A,
            onPointerMove: R,
            onPointerUp: B
          }
        ),
        /* @__PURE__ */ e("div", { className: "meso-main__artifact", children: h })
      ] }) : n })
    ] })
  ] });
}
function Y({
  role: r,
  content: a,
  streaming: t = !1,
  timestamp: s,
  markdown: n = !1,
  renderMarkdown: c
}) {
  const u = n && typeof c == "function";
  return /* @__PURE__ */ o("div", { className: `meso-bubble meso-bubble--${r}`, children: [
    r === "assistant" && /* @__PURE__ */ e("div", { className: "meso-bubble__avatar", "aria-hidden": "true", children: "AI" }),
    /* @__PURE__ */ o("div", { className: "meso-bubble__body", children: [
      u ? /* @__PURE__ */ e(
        "div",
        {
          className: "meso-bubble__content meso-bubble__md",
          dangerouslySetInnerHTML: { __html: c(a) }
        }
      ) : /* @__PURE__ */ o("div", { className: "meso-bubble__content", children: [
        a.split(`
`).map((m, h) => /* @__PURE__ */ o(Z.Fragment, { children: [
          h > 0 && /* @__PURE__ */ e("br", {}),
          m
        ] }, h)),
        t && /* @__PURE__ */ e("span", { className: "meso-bubble__cursor", "aria-hidden": "true", children: "▋" })
      ] }),
      s && /* @__PURE__ */ e("div", { className: "meso-bubble__timestamp", children: s })
    ] })
  ] });
}
function ie({ content: r, streaming: a = !1, autoCollapseDelay: t = 1500 }) {
  const [s, n] = w(!0), c = $(a);
  return O(() => {
    if (c.current && !a) {
      const u = setTimeout(() => n(!1), t);
      return () => clearTimeout(u);
    }
    c.current = a;
  }, [a, t]), /* @__PURE__ */ o("div", { className: `meso-think${s ? " meso-think--open" : ""}`, children: [
    /* @__PURE__ */ o(
      "button",
      {
        className: "meso-think__header",
        onClick: () => n(!s),
        "aria-expanded": s,
        children: [
          /* @__PURE__ */ e("svg", { className: "meso-think__chevron", width: "14", height: "14", viewBox: "0 0 14 14", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ e("polyline", { points: "3,5 7,9 11,5" }) }),
          /* @__PURE__ */ e("span", { className: "meso-think__label", children: "思考过程" }),
          a && /* @__PURE__ */ e("span", { className: "meso-think__dot", "aria-label": "思考中" })
        ]
      }
    ),
    /* @__PURE__ */ e("div", { className: "meso-think__body", children: /* @__PURE__ */ o("div", { className: "meso-think__content", children: [
      r,
      a && /* @__PURE__ */ e("span", { className: "meso-think__cursor", "aria-hidden": "true", children: "▋" })
    ] }) })
  ] });
}
function Ie({ active: r = !0 }) {
  return r ? /* @__PURE__ */ e("span", { className: "meso-streaming-cursor", "aria-hidden": "true", children: "▋" }) : null;
}
function le(r) {
  try {
    const a = JSON.parse(r);
    return Array.isArray(a.headers) && Array.isArray(a.rows) ? a : null;
  } catch {
    return null;
  }
}
function ce({
  type: r,
  content: a,
  language: t = "plaintext",
  streaming: s = !1,
  onCopy: n,
  onDownload: c,
  renderMermaid: u,
  highlightCode: m,
  renderMarkdown: h
}) {
  const [l, f] = w(!1), [b, k] = w(r), [p, L] = w(null), [i, _] = w(!1), [x, S] = w(null), C = $("");
  O(() => {
    k(r);
  }, [r]), O(() => {
    r !== "mermaid" || s || !u || a === C.current || (C.current = a, L(null), _(!1), u(a).then((y) => L(y)).catch(() => _(!0)));
  }, [r, s, a, u]), O(() => {
    r !== "code" || s || !m || a === C.current && x || (C.current = a, S(m(a, t)));
  }, [r, s, a, t, m, x]);
  const A = () => {
    navigator.clipboard.writeText(a).catch(() => {
    }), f(!0), setTimeout(() => f(!1), 2e3), n == null || n(a);
  }, R = () => {
    if (c) {
      c(a);
      return;
    }
    const y = {
      html: "html",
      mermaid: "md",
      markdown: "md",
      table: "json",
      code: t || "txt"
    }, v = new Blob([a], { type: "text/plain" }), g = document.createElement("a");
    g.href = URL.createObjectURL(v), g.download = `artifact.${y[r]}`, g.click(), URL.revokeObjectURL(g.href);
  };
  return /* @__PURE__ */ o("div", { className: "meso-artifact", children: [
    /* @__PURE__ */ o("div", { className: "meso-artifact__header", children: [
      /* @__PURE__ */ e("div", { className: "meso-artifact__tabs", children: (r === "html" ? ["html", "code"] : [r]).map((y) => /* @__PURE__ */ e(
        "span",
        {
          className: `meso-artifact__tab${b === y ? " meso-artifact__tab--active" : ""}`,
          onClick: () => k(y),
          children: me(y, t)
        },
        y
      )) }),
      s && /* @__PURE__ */ e("span", { className: "meso-artifact__streaming-badge", children: "生成中…" }),
      /* @__PURE__ */ e("button", { className: "meso-artifact__download-btn", onClick: R, title: "下载", "aria-label": "下载文件", children: /* @__PURE__ */ e("svg", { width: "15", height: "15", viewBox: "0 0 15 15", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ e("path", { d: "M7.5 2v8M4.5 7.5L7.5 10.5 10.5 7.5M2 13h11" }) }) }),
      /* @__PURE__ */ e("button", { className: "meso-artifact__copy-btn", onClick: A, title: "复制", "aria-label": "复制代码", children: l ? /* @__PURE__ */ e("svg", { width: "15", height: "15", viewBox: "0 0 15 15", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ e("polyline", { points: "2,8 6,12 13,4" }) }) : /* @__PURE__ */ o("svg", { width: "15", height: "15", viewBox: "0 0 15 15", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round", children: [
        /* @__PURE__ */ e("rect", { x: "5", y: "5", width: "8", height: "9", rx: "1.5" }),
        /* @__PURE__ */ e("path", { d: "M10 5V3.5A1.5 1.5 0 008.5 2h-6A1.5 1.5 0 001 3.5v9A1.5 1.5 0 002.5 14H4" })
      ] }) })
    ] }),
    /* @__PURE__ */ o("div", { className: "meso-artifact__body", children: [
      b === "html" && /* @__PURE__ */ e("iframe", { className: "meso-artifact__preview", srcDoc: a, sandbox: "allow-scripts", title: "HTML 预览" }),
      b === "mermaid" && /* @__PURE__ */ o(M, { children: [
        s && /* @__PURE__ */ o("pre", { className: "meso-artifact__code", children: [
          /* @__PURE__ */ e("code", { children: a }),
          /* @__PURE__ */ e("span", { className: "meso-artifact__cursor", "aria-hidden": "true", children: "▋" })
        ] }),
        !s && p && /* @__PURE__ */ e(
          "div",
          {
            className: "meso-artifact__mermaid",
            dangerouslySetInnerHTML: { __html: p }
          }
        ),
        !s && !p && !i && !u && /* @__PURE__ */ o("div", { className: "meso-artifact__mermaid-placeholder", children: [
          /* @__PURE__ */ e("span", { children: "图表预览需要集成 Mermaid 渲染器" }),
          /* @__PURE__ */ e("pre", { className: "meso-artifact__code", style: { flex: 1 }, children: /* @__PURE__ */ e("code", { children: a }) })
        ] }),
        !s && i && /* @__PURE__ */ o("div", { className: "meso-artifact__mermaid-placeholder meso-artifact__mermaid-placeholder--error", children: [
          /* @__PURE__ */ e("span", { children: "图表渲染失败，请检查语法" }),
          /* @__PURE__ */ e("pre", { className: "meso-artifact__code", style: { flex: 1 }, children: /* @__PURE__ */ e("code", { children: a }) })
        ] }),
        !s && !p && !i && u && /* @__PURE__ */ e("div", { className: "meso-artifact__mermaid-placeholder", children: /* @__PURE__ */ e("span", { children: "渲染中…" }) })
      ] }),
      b === "markdown" && /* @__PURE__ */ e(M, { children: h ? /* @__PURE__ */ e(
        "div",
        {
          className: "meso-artifact__markdown",
          dangerouslySetInnerHTML: { __html: h(a) }
        }
      ) : /* @__PURE__ */ o("pre", { className: "meso-artifact__code", children: [
        /* @__PURE__ */ e("code", { children: a }),
        s && /* @__PURE__ */ e("span", { className: "meso-artifact__cursor", "aria-hidden": "true", children: "▋" })
      ] }) }),
      b === "table" && /* @__PURE__ */ e(de, { content: a, streaming: s }),
      (b === "code" || b === "html" && !1) && /* @__PURE__ */ o("pre", { className: "meso-artifact__code", children: [
        x && !s ? /* @__PURE__ */ e("code", { dangerouslySetInnerHTML: { __html: x } }) : /* @__PURE__ */ e("code", { children: a }),
        s && /* @__PURE__ */ e("span", { className: "meso-artifact__cursor", "aria-hidden": "true", children: "▋" })
      ] })
    ] })
  ] });
}
function de({ content: r, streaming: a }) {
  const t = le(r);
  return t ? /* @__PURE__ */ e("div", { className: "meso-artifact__table-wrap", children: /* @__PURE__ */ o("table", { className: "meso-artifact__table", children: [
    /* @__PURE__ */ e("thead", { children: /* @__PURE__ */ e("tr", { children: t.headers.map((s, n) => /* @__PURE__ */ e("th", { children: s }, n)) }) }),
    /* @__PURE__ */ e("tbody", { children: t.rows.map((s, n) => /* @__PURE__ */ e("tr", { children: s.map((c, u) => /* @__PURE__ */ e("td", { children: String(c) }, u)) }, n)) })
  ] }) }) : /* @__PURE__ */ o("pre", { className: "meso-artifact__code", children: [
    /* @__PURE__ */ e("code", { children: r }),
    a && /* @__PURE__ */ e("span", { className: "meso-artifact__cursor", "aria-hidden": "true", children: "▋" })
  ] });
}
function me(r, a) {
  return r === "html" ? "HTML 预览" : r === "mermaid" ? "图表" : r === "markdown" ? "Markdown" : r === "table" ? "表格" : a || "Code";
}
function he({ stages: r, compact: a = !1 }) {
  return r.length === 0 ? null : /* @__PURE__ */ e("div", { className: `meso-stages${a ? " meso-stages--compact" : ""}`, role: "status", "aria-label": "处理进度", children: r.map((t, s) => /* @__PURE__ */ o(
    "div",
    {
      className: `meso-stage meso-stage--${t.status}`,
      children: [
        /* @__PURE__ */ e("div", { className: "meso-stage__dot", children: t.status === "done" ? /* @__PURE__ */ e("svg", { width: "10", height: "10", viewBox: "0 0 10 10", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ e("polyline", { points: "1.5,5.5 4,8 8.5,2.5" }) }) : /* @__PURE__ */ e("span", { className: "meso-stage__dot-inner" }) }),
        s < r.length - 1 && /* @__PURE__ */ e("div", { className: `meso-stage__line${t.status === "done" ? " meso-stage__line--done" : ""}` }),
        !a && /* @__PURE__ */ e("span", { className: "meso-stage__label", children: t.label }),
        a && /* @__PURE__ */ e("span", { className: "meso-stage__label meso-stage__label--compact", children: t.label })
      ]
    },
    t.id
  )) });
}
function ue({ state: r }) {
  return r === "done" ? /* @__PURE__ */ e("svg", { className: "meso-wf-node__icon meso-wf-node__icon--done", viewBox: "0 0 12 12", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: /* @__PURE__ */ e("polyline", { points: "1.5,6.5 4.5,9.5 10.5,3" }) }) : r === "error" ? /* @__PURE__ */ o("svg", { className: "meso-wf-node__icon meso-wf-node__icon--error", viewBox: "0 0 12 12", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", children: [
    /* @__PURE__ */ e("line", { x1: "2", y1: "2", x2: "10", y2: "10" }),
    /* @__PURE__ */ e("line", { x1: "10", y1: "2", x2: "2", y2: "10" })
  ] }) : r === "skipped" ? /* @__PURE__ */ e("svg", { className: "meso-wf-node__icon meso-wf-node__icon--skipped", viewBox: "0 0 12 12", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", children: /* @__PURE__ */ e("line", { x1: "2", y1: "6", x2: "10", y2: "6" }) }) : /* @__PURE__ */ e("span", { className: "meso-wf-node__spinner", "aria-hidden": "true" });
}
function _e(r) {
  return r < 1e3 ? `${r}ms` : `${(r / 1e3).toFixed(1)}s`;
}
function fe({ node: r, depth: a, isLast: t }) {
  const [s, n] = w(!1), c = r.metadata && Object.keys(r.metadata).length > 0;
  return /* @__PURE__ */ o("div", { className: `meso-wf-node meso-wf-node--${r.state}`, style: { "--meso-wf-depth": a }, children: [
    /* @__PURE__ */ o("div", { className: "meso-wf-node__track", children: [
      /* @__PURE__ */ e("div", { className: "meso-wf-node__dot", children: /* @__PURE__ */ e(ue, { state: r.state }) }),
      !t && /* @__PURE__ */ e("div", { className: "meso-wf-node__line" })
    ] }),
    /* @__PURE__ */ o("div", { className: "meso-wf-node__body", children: [
      /* @__PURE__ */ o("div", { className: "meso-wf-node__header", children: [
        /* @__PURE__ */ e("code", { className: "meso-wf-node__name", children: r.name }),
        r.duration_ms !== void 0 && /* @__PURE__ */ e("span", { className: "meso-wf-node__duration", children: _e(r.duration_ms) }),
        c && /* @__PURE__ */ e(
          "button",
          {
            className: "meso-wf-node__expand",
            onClick: () => n((u) => !u),
            "aria-expanded": s,
            "aria-label": s ? "收起详情" : "展开详情",
            children: /* @__PURE__ */ e("svg", { viewBox: "0 0 10 10", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", style: { transform: s ? "rotate(180deg)" : void 0 }, children: /* @__PURE__ */ e("polyline", { points: "2,3.5 5,6.5 8,3.5" }) })
          }
        )
      ] }),
      s && c && /* @__PURE__ */ e("pre", { className: "meso-wf-node__meta", children: JSON.stringify(r.metadata, null, 2) })
    ] })
  ] });
}
function pe(r) {
  const { nodes: a, nodeOrder: t } = r, s = /* @__PURE__ */ new Map(), n = [];
  for (const c of t) {
    const u = a[c];
    if (!u) continue;
    const m = u.parent_id ? (s.get(u.parent_id) ?? 0) + 1 : 0;
    s.set(c, m), n.push({ node: u, depth: m });
  }
  return n;
}
function Be({ runs: r, showRunId: a = !0 }) {
  if (r.length === 0) return null;
  const t = r.length > 1;
  return /* @__PURE__ */ e("div", { className: "meso-wf", role: "status", "aria-label": "工作流进度", children: r.map((s) => {
    const n = pe(s);
    return /* @__PURE__ */ o("div", { className: "meso-wf-run", children: [
      (t || a) && t && /* @__PURE__ */ e("div", { className: "meso-wf-run__label", children: s.run_id }),
      n.map(({ node: c, depth: u }, m) => /* @__PURE__ */ e(
        fe,
        {
          node: c,
          depth: u,
          isLast: m === n.length - 1
        },
        c.node_id
      ))
    ] }, s.run_id);
  }) });
}
const ve = {
  safe: "只读",
  write: "写入",
  destructive: "危险"
}, z = {
  mcp: "MCP",
  api: "API",
  local: "本地"
};
function Ne({ toolCall: r, onConfirm: a, onCancel: t }) {
  var k;
  const [s, n] = w(!1), [c, u] = w(!1), { call: m, result: h, status: l } = r, f = m.risk ?? "safe", b = Object.keys(m.args).length > 0;
  return /* @__PURE__ */ o("div", { className: `meso-tool meso-tool--${l} meso-tool--risk-${f}`, children: [
    /* @__PURE__ */ o("div", { className: "meso-tool__header", children: [
      /* @__PURE__ */ e(be, { status: l }),
      /* @__PURE__ */ e("span", { className: "meso-tool__name", children: m.name }),
      m.provider && z[m.provider] && /* @__PURE__ */ e("span", { className: `meso-tool__provider meso-tool__provider--${m.provider}`, children: z[m.provider] }),
      ((k = m.annotations) == null ? void 0 : k.open_world) && /* @__PURE__ */ e("span", { className: "meso-tool__annotation", title: "此工具会访问外部网络", children: "🌐" }),
      f !== "safe" && /* @__PURE__ */ e("span", { className: `meso-tool__risk meso-tool__risk--${f}`, children: ve[f] }),
      (h == null ? void 0 : h.duration_ms) !== void 0 && /* @__PURE__ */ o("span", { className: "meso-tool__duration", children: [
        h.duration_ms,
        "ms"
      ] }),
      b && /* @__PURE__ */ o(
        "button",
        {
          className: "meso-tool__toggle",
          onClick: () => n((p) => !p),
          "aria-expanded": s,
          "aria-label": s ? "折叠参数" : "展开参数",
          children: [
            s ? "▾" : "▸",
            " 参数"
          ]
        }
      )
    ] }),
    s && b && /* @__PURE__ */ e("pre", { className: "meso-tool__args", children: JSON.stringify(m.args, null, 2) }),
    l === "awaiting_confirm" && /* @__PURE__ */ o("div", { className: "meso-tool__confirm", children: [
      /* @__PURE__ */ e("span", { className: "meso-tool__confirm-msg", children: "此操作需要确认后执行" }),
      /* @__PURE__ */ o("div", { className: "meso-tool__confirm-actions", children: [
        /* @__PURE__ */ e(
          "button",
          {
            className: "meso-tool__btn meso-tool__btn--cancel",
            onClick: () => t == null ? void 0 : t(m.id),
            children: "取消"
          }
        ),
        /* @__PURE__ */ e(
          "button",
          {
            className: `meso-tool__btn meso-tool__btn--confirm meso-tool__btn--${f}`,
            onClick: () => a == null ? void 0 : a(m.id),
            children: f === "destructive" ? "确认执行（不可撤销）" : "确认"
          }
        )
      ] })
    ] }),
    (l === "done" || l === "error") && h && /* @__PURE__ */ o("div", { className: "meso-tool__result", children: [
      /* @__PURE__ */ o(
        "button",
        {
          className: "meso-tool__toggle",
          onClick: () => u((p) => !p),
          "aria-expanded": c,
          "aria-label": c ? "折叠结果" : "展开结果",
          children: [
            c ? "▾" : "▸",
            " ",
            l === "error" ? "错误" : "结果"
          ]
        }
      ),
      c && /* @__PURE__ */ e("pre", { className: `meso-tool__output${l === "error" ? " meso-tool__output--error" : ""}`, children: l === "error" ? h.error : h.output })
    ] })
  ] });
}
function be({ status: r }) {
  switch (r) {
    case "pending":
    case "running":
      return /* @__PURE__ */ e("span", { className: "meso-tool__spinner", "aria-label": "执行中" });
    case "awaiting_confirm":
      return /* @__PURE__ */ o("svg", { className: "meso-tool__icon meso-tool__icon--warn", width: "14", height: "14", viewBox: "0 0 14 14", fill: "none", "aria-label": "等待确认", children: [
        /* @__PURE__ */ e("circle", { cx: "7", cy: "7", r: "6", stroke: "currentColor", strokeWidth: "1.5" }),
        /* @__PURE__ */ e("path", { d: "M7 4v4M7 10v.5", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round" })
      ] });
    case "done":
      return /* @__PURE__ */ o("svg", { className: "meso-tool__icon meso-tool__icon--done", width: "14", height: "14", viewBox: "0 0 14 14", fill: "none", "aria-label": "完成", children: [
        /* @__PURE__ */ e("circle", { cx: "7", cy: "7", r: "6", stroke: "currentColor", strokeWidth: "1.5" }),
        /* @__PURE__ */ e("polyline", { points: "4,7 6,9.5 10,4.5", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round" })
      ] });
    case "error":
      return /* @__PURE__ */ o("svg", { className: "meso-tool__icon meso-tool__icon--error", width: "14", height: "14", viewBox: "0 0 14 14", fill: "none", "aria-label": "失败", children: [
        /* @__PURE__ */ e("circle", { cx: "7", cy: "7", r: "6", stroke: "currentColor", strokeWidth: "1.5" }),
        /* @__PURE__ */ e("path", { d: "M5 5l4 4M9 5l-4 4", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round" })
      ] });
  }
}
function ke({ soul: r, compact: a = !1 }) {
  const t = r.name.charAt(0);
  return /* @__PURE__ */ o(
    "div",
    {
      className: `meso-soul${a ? " meso-soul--compact" : ""}`,
      title: `${r.name} v${r.version}`,
      role: "status",
      "aria-label": `当前 Soul: ${r.name}`,
      children: [
        /* @__PURE__ */ e("div", { className: "meso-soul__avatar", children: r.avatar ? /* @__PURE__ */ e("img", { src: r.avatar, alt: r.name, className: "meso-soul__img" }) : /* @__PURE__ */ e("span", { className: "meso-soul__initial", children: t }) }),
        !a && /* @__PURE__ */ o(M, { children: [
          /* @__PURE__ */ e("span", { className: "meso-soul__name", children: r.name }),
          r.traits && r.traits.length > 0 && /* @__PURE__ */ e("div", { className: "meso-soul__traits", children: r.traits.map((s) => /* @__PURE__ */ e("span", { className: "meso-soul__trait", children: s }, s)) })
        ] })
      ]
    }
  );
}
const ge = {
  mcp: "MCP",
  api: "API"
};
function we({ skill: r }) {
  const a = r.provider ? ge[r.provider] : null;
  return /* @__PURE__ */ o(
    "div",
    {
      className: "meso-skill",
      title: r.description ?? r.name,
      role: "status",
      "aria-label": `当前技能: ${r.name}`,
      children: [
        /* @__PURE__ */ e("svg", { className: "meso-skill__icon", width: "12", height: "12", viewBox: "0 0 12 12", fill: "none", "aria-hidden": "true", children: /* @__PURE__ */ e(
          "path",
          {
            d: "M6 1L7.5 4.5H11L8 6.5L9 10L6 8L3 10L4 6.5L1 4.5H4.5L6 1Z",
            stroke: "currentColor",
            strokeWidth: "1.2",
            strokeLinejoin: "round"
          }
        ) }),
        /* @__PURE__ */ e("span", { className: "meso-skill__name", children: r.name }),
        r.focus && r.focus.length > 0 && /* @__PURE__ */ o("span", { className: "meso-skill__focus", children: [
          "· ",
          r.focus.join(", ")
        ] }),
        a && /* @__PURE__ */ e("span", { className: "meso-skill__provider", children: a })
      ]
    }
  );
}
function ye({ resourceRead: r }) {
  const [a, t] = w(!1), { read: s, content: n, status: c } = r, u = s.name ?? s.uri, m = s.server;
  return /* @__PURE__ */ o("div", { className: `meso-resource meso-resource--${c}`, children: [
    /* @__PURE__ */ o("div", { className: "meso-resource__header", children: [
      /* @__PURE__ */ e(xe, { status: c }),
      /* @__PURE__ */ e("span", { className: "meso-resource__uri", title: s.uri, children: u }),
      m && /* @__PURE__ */ e("span", { className: "meso-resource__server", children: m }),
      (n == null ? void 0 : n.duration_ms) !== void 0 && /* @__PURE__ */ o("span", { className: "meso-resource__duration", children: [
        n.duration_ms,
        "ms"
      ] }),
      (c === "done" || c === "error") && n && /* @__PURE__ */ o(
        "button",
        {
          className: "meso-resource__toggle",
          onClick: () => t((h) => !h),
          "aria-expanded": a,
          "aria-label": a ? "折叠内容" : "展开内容",
          children: [
            a ? "▾" : "▸",
            " ",
            c === "error" ? "错误" : "内容"
          ]
        }
      )
    ] }),
    a && n && /* @__PURE__ */ e("div", { className: "meso-resource__content", children: c === "error" ? /* @__PURE__ */ e("pre", { className: "meso-resource__text meso-resource__text--error", children: n.error }) : n.contents.map((h, l) => /* @__PURE__ */ o("div", { children: [
      h.type === "text" && /* @__PURE__ */ e("pre", { className: "meso-resource__text", children: h.text }),
      h.type === "image" && h.data && /* @__PURE__ */ e(
        "img",
        {
          className: "meso-resource__image",
          src: `data:${h.mime_type ?? "image/png"};base64,${h.data}`,
          alt: "resource"
        }
      ),
      h.type === "blob" && /* @__PURE__ */ o("span", { className: "meso-resource__blob-label", children: [
        "[",
        h.mime_type ?? "binary",
        "]"
      ] })
    ] }, l)) })
  ] });
}
function xe({ status: r }) {
  switch (r) {
    case "pending":
      return /* @__PURE__ */ e("span", { className: "meso-resource__spinner", "aria-label": "读取中" });
    case "done":
      return /* @__PURE__ */ e("svg", { className: "meso-resource__icon meso-resource__icon--done", width: "13", height: "13", viewBox: "0 0 13 13", fill: "none", "aria-label": "完成", children: /* @__PURE__ */ e("path", { d: "M2 7L5 10L11 4", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round" }) });
    case "error":
      return /* @__PURE__ */ o("svg", { className: "meso-resource__icon meso-resource__icon--error", width: "13", height: "13", viewBox: "0 0 13 13", fill: "none", "aria-label": "失败", children: [
        /* @__PURE__ */ e("circle", { cx: "6.5", cy: "6.5", r: "5.5", stroke: "currentColor", strokeWidth: "1.2" }),
        /* @__PURE__ */ e("path", { d: "M4.5 4.5l4 4M8.5 4.5l-4 4", stroke: "currentColor", strokeWidth: "1.2", strokeLinecap: "round" })
      ] });
  }
}
function Le(r) {
  return r === "html preview" ? { type: "html" } : r === "mermaid" ? { type: "mermaid" } : r === "markdown" ? { type: "markdown" } : r === "table" ? { type: "table" } : { type: "code", language: r };
}
function Me({
  messages: r,
  streaming: a,
  onArtifactCopy: t,
  onArtifactDownload: s,
  onToolConfirm: n,
  onToolCancel: c,
  emptyState: u,
  className: m,
  renderExtension: h,
  renderMarkdown: l,
  renderMermaid: f,
  highlightCode: b
}) {
  const k = $(null);
  O(() => {
    var i;
    (i = k.current) == null || i.scrollIntoView({ behavior: "smooth" });
  }, [r, a]);
  const p = r.length > 0 || a && a.status !== "idle", L = a ? a.stages.every((i) => i.state === "done" || i.state === "error") : !0;
  return /* @__PURE__ */ e("div", { className: `meso-message-list${m ? ` ${m}` : ""}`, children: /* @__PURE__ */ o("div", { className: "meso-message-list__inner", children: [
    !p && u && /* @__PURE__ */ e("div", { className: "meso-message-list__empty", children: u }),
    r.map((i) => /* @__PURE__ */ e(
      Y,
      {
        role: i.role,
        content: i.content,
        timestamp: i.timestamp,
        markdown: i.role === "assistant",
        renderMarkdown: l
      },
      i.id
    )),
    a && a.status !== "idle" && /* @__PURE__ */ o("div", { className: "meso-message-list__live", children: [
      (a.activeSoul || a.activeSkill) && /* @__PURE__ */ o("div", { className: "meso-message-list__context-row", children: [
        a.activeSoul && /* @__PURE__ */ e(ke, { soul: a.activeSoul }),
        a.activeSkill && /* @__PURE__ */ e(we, { skill: a.activeSkill })
      ] }),
      a.stages.length > 0 && !L && /* @__PURE__ */ e(
        he,
        {
          stages: a.stages.map((i) => ({
            id: i.name,
            label: i.name,
            status: i.state === "done" || i.state === "error" ? "done" : "active"
          }))
        }
      ),
      a.memorySnippets.length > 0 && /* @__PURE__ */ e("div", { className: "meso-memory-chips", children: a.memorySnippets.map((i, _) => /* @__PURE__ */ o("span", { className: "meso-memory-chip", title: i.content, children: [
        "[",
        i.category,
        "] ",
        i.content
      ] }, _)) }),
      a.resourceReadOrder.length > 0 && /* @__PURE__ */ e("div", { className: "meso-message-list__resources", children: a.resourceReadOrder.map((i) => {
        const _ = a.resourceReads[i];
        return _ ? /* @__PURE__ */ e(ye, { resourceRead: _ }, i) : null;
      }) }),
      a.toolCallOrder.length > 0 && /* @__PURE__ */ e("div", { className: "meso-message-list__tools", children: a.toolCallOrder.map((i) => {
        const _ = a.toolCalls[i];
        return _ ? /* @__PURE__ */ e(
          Ne,
          {
            toolCall: _,
            onConfirm: n,
            onCancel: c
          },
          i
        ) : null;
      }) }),
      h && a.extensionLog.length > 0 && /* @__PURE__ */ e("div", { className: "meso-message-list__extensions", children: a.extensionLog.map((i, _) => /* @__PURE__ */ e(Z.Fragment, { children: h(i) }, _)) }),
      a.thinkContent && /* @__PURE__ */ e(
        ie,
        {
          content: a.thinkContent,
          streaming: !a.thinkDone
        }
      ),
      (a.textContent || a.status === "streaming") && /* @__PURE__ */ e(
        Y,
        {
          role: "assistant",
          content: a.textContent,
          streaming: a.status === "streaming" && a.artifactOrder.length === 0,
          markdown: !0,
          renderMarkdown: l
        }
      ),
      a.artifactOrder.map((i) => {
        const _ = a.artifacts[i];
        if (!_) return null;
        const { type: x, language: S } = Le(_.lang);
        return /* @__PURE__ */ e(
          ce,
          {
            type: x,
            content: _.content,
            language: S,
            streaming: !_.done,
            onCopy: t,
            onDownload: s,
            renderMermaid: f,
            highlightCode: b,
            renderMarkdown: l
          },
          i
        );
      }),
      a.memorySaved.length > 0 && /* @__PURE__ */ e("div", { className: "meso-memory-saved", children: a.memorySaved.map((i) => /* @__PURE__ */ o("span", { className: "meso-memory-saved__chip", title: i.preview, children: [
        /* @__PURE__ */ e("svg", { width: "10", height: "10", viewBox: "0 0 10 10", fill: "none", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", children: /* @__PURE__ */ e("path", { d: "M2 9V2a1 1 0 011-1h4a1 1 0 011 1v7L5 7.5 2 9z" }) }),
        "已记忆 [",
        i.category,
        "]"
      ] }, i.id)) })
    ] }),
    /* @__PURE__ */ e("div", { ref: k })
  ] }) });
}
const Se = {
  safe: { label: "只读操作", confirmText: "确认" },
  write: { label: "写入操作", confirmText: "确认执行" },
  destructive: { label: "危险操作", confirmText: "确认执行（不可撤销）" }
};
function We({ toolCall: r, onConfirm: a, onCancel: t }) {
  const s = r.risk ?? "safe", n = Se[s], c = Object.keys(r.args).length > 0;
  return /* @__PURE__ */ o("div", { className: `meso-confirm-gate meso-confirm-gate--${s}`, role: "alertdialog", "aria-label": "工具执行确认", children: [
    /* @__PURE__ */ e("div", { className: "meso-confirm-gate__icon", children: /* @__PURE__ */ o("svg", { width: "20", height: "20", viewBox: "0 0 20 20", fill: "none", "aria-hidden": "true", children: [
      /* @__PURE__ */ e("circle", { cx: "10", cy: "10", r: "9", stroke: "currentColor", strokeWidth: "1.5" }),
      /* @__PURE__ */ e("path", { d: "M10 6v5M10 13.5v.5", stroke: "currentColor", strokeWidth: "1.5", strokeLinecap: "round" })
    ] }) }),
    /* @__PURE__ */ o("div", { className: "meso-confirm-gate__body", children: [
      /* @__PURE__ */ o("div", { className: "meso-confirm-gate__title", children: [
        /* @__PURE__ */ e("span", { className: `meso-confirm-gate__risk-badge meso-confirm-gate__risk-badge--${s}`, children: n.label }),
        /* @__PURE__ */ e("code", { className: "meso-confirm-gate__tool-name", children: r.name })
      ] }),
      c && /* @__PURE__ */ e("pre", { className: "meso-confirm-gate__args", children: JSON.stringify(r.args, null, 2) }),
      /* @__PURE__ */ o("div", { className: "meso-confirm-gate__actions", children: [
        /* @__PURE__ */ e(
          "button",
          {
            className: "meso-confirm-gate__btn meso-confirm-gate__btn--cancel",
            onClick: () => t(r.id),
            children: "取消"
          }
        ),
        /* @__PURE__ */ e(
          "button",
          {
            className: `meso-confirm-gate__btn meso-confirm-gate__btn--confirm meso-confirm-gate__btn--${s}`,
            onClick: () => a(r.id),
            children: n.confirmText
          }
        )
      ] })
    ] })
  ] });
}
function Ee(r, a) {
  const [t, s] = w(V), n = $(null), c = $(a);
  c.current = a;
  const u = T(() => {
    var l;
    (l = n.current) == null || l.abort(), s((f) => ({ ...f, status: "idle" }));
  }, []), m = T(() => {
    var l;
    (l = n.current) == null || l.abort(), s(V());
  }, []), h = T(async (l) => {
    var L, i, _, x, S, C, A, R, B, y, v, g, W, E, j, F;
    (L = n.current) == null || L.abort();
    const f = new AbortController();
    n.current = f;
    const b = { ...V(), status: "streaming" };
    s(b);
    let k = b;
    const p = (l == null ? void 0 : l.method) ?? (l != null && l.body ? "POST" : "GET");
    try {
      const I = await fetch(r, {
        method: p,
        headers: {
          ...p === "POST" ? { "Content-Type": "application/json" } : {},
          ...l == null ? void 0 : l.headers
        },
        body: l != null && l.body ? JSON.stringify(l.body) : void 0,
        signal: f.signal
      });
      if (!I.ok) throw new Error(`HTTP ${I.status}`);
      const P = I.body.getReader(), H = new TextDecoder();
      let U = "";
      for (; ; ) {
        const { done: ee, value: re } = await P.read();
        if (ee) break;
        U += H.decode(re, { stream: !0 });
        const J = U.split(`
`);
        U = J.pop() ?? "";
        for (const ae of J) {
          const N = se(ae);
          if (!N) continue;
          const D = oe(k, N);
          k = D, s(D);
          const d = c.current;
          if (d)
            switch (N.type) {
              case "capabilities":
                (i = d.onCapabilities) == null || i.call(d, N.payload);
                break;
              case "stage":
                (_ = d.onStageChange) == null || _.call(d, N.payload);
                break;
              case "memory":
                (x = d.onMemoryRecalled) == null || x.call(d, N.payload.snippets);
                break;
              case "memory_saved":
                (S = d.onMemorySaved) == null || S.call(d, N.payload);
                break;
              case "soul":
                (C = d.onSoulActivated) == null || C.call(d, N.payload);
                break;
              case "skill_active":
                (A = d.onSkillActivated) == null || A.call(d, N.payload);
                break;
              case "tool_call":
                (R = d.onToolCall) == null || R.call(d, N.payload);
                break;
              case "tool_result":
                (B = d.onToolResult) == null || B.call(d, N.payload);
                break;
              case "resource_read":
                (y = d.onResourceRead) == null || y.call(d, N.payload);
                break;
              case "resource_content":
                (v = d.onResourceContent) == null || v.call(d, N.payload);
                break;
              case "artifact": {
                const G = D.artifacts[N.payload.id];
                G && ((g = d.onArtifact) == null || g.call(d, G));
                break;
              }
              case "error":
                (W = d.onError) == null || W.call(d, N.payload.message, N.payload.code);
                break;
              case "done":
                (E = d.onDone) == null || E.call(d, D);
                break;
            }
          if (N.type === "done" || N.type === "error") return;
        }
      }
    } catch (I) {
      if (I.name === "AbortError") return;
      const P = I.message;
      s((H) => ({ ...H, status: "error", errorMessage: P })), (F = (j = c.current) == null ? void 0 : j.onError) == null || F.call(j, P);
    }
  }, [r]);
  return { state: t, start: h, abort: u, reset: m };
}
const K = "meso-theme";
function Ce() {
  return typeof window > "u" ? "light" : localStorage.getItem(K) ?? "light";
}
function Te(r) {
  document.documentElement.setAttribute("data-theme", r), localStorage.setItem(K, r);
}
function je() {
  const [r, a] = w(Ce);
  O(() => {
    Te(r);
  }, [r]);
  const t = T(() => {
    a((s) => s === "light" ? "dark" : "light");
  }, []);
  return { theme: r, toggle: t };
}
export {
  ce as ArtifactPanel,
  Y as ChatBubble,
  We as ConfirmGate,
  Me as MessageList,
  He as PROTOCOL_VERSION,
  ye as ResourceReadBlock,
  we as SkillIndicator,
  ke as SoulIndicator,
  he as StageTimeline,
  Ie as StreamingCursor,
  ie as ThinkBlock,
  Re as ThreeColumnLayout,
  Ne as ToolCallBlock,
  Be as WorkflowTimeline,
  oe as applyEvent,
  V as createInitialStreamState,
  se as parseSSELine,
  Ee as useSSEStream,
  je as useTheme
};
