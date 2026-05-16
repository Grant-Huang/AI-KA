import { describe, it, expect } from "vitest";
import { parseUrl, buildUrl, DEFAULT_NAV, NavState } from "../navigation";

// ── parseUrl ──────────────────────────────────────────────────────────────────

describe("parseUrl", () => {
  it("/ → review default", () => {
    expect(parseUrl("/")).toEqual(DEFAULT_NAV);
  });

  it("/review → review default", () => {
    expect(parseUrl("/review")).toEqual(DEFAULT_NAV);
  });

  it("/review/project/:pid → review, selectedId", () => {
    expect(parseUrl("/review/project/5")).toEqual({
      ...DEFAULT_NAV,
      selectedId: 5,
    });
  });

  it("/review/project/:pid/conversation/:cid → review + project + conversation", () => {
    expect(parseUrl("/review/project/5/conversation/42")).toEqual({
      ...DEFAULT_NAV,
      selectedId: 5,
      selectedConversationId: 42,
    });
  });

  it("/review/conversation/:cid → review, no project, conversation", () => {
    expect(parseUrl("/review/conversation/7")).toEqual({
      ...DEFAULT_NAV,
      selectedConversationId: 7,
    });
  });

  it("/review/rules → result_review tab", () => {
    expect(parseUrl("/review/rules")).toEqual({
      ...DEFAULT_NAV,
      reviewMainTab: "result_review",
    });
  });

  it("/review/rules/project/:pid → result_review + project", () => {
    expect(parseUrl("/review/rules/project/3")).toEqual({
      ...DEFAULT_NAV,
      reviewMainTab: "result_review",
      selectedId: 3,
    });
  });

  it("/review/ingest → ingest panel", () => {
    expect(parseUrl("/review/ingest")).toEqual({
      ...DEFAULT_NAV,
      mainPanel: "ingest",
    });
  });

  it("/review/ingest/project/:pid → ingest + project", () => {
    expect(parseUrl("/review/ingest/project/7")).toEqual({
      ...DEFAULT_NAV,
      mainPanel: "ingest",
      selectedId: 7,
    });
  });

  it("/review/domain → review_domain panel", () => {
    expect(parseUrl("/review/domain")).toEqual({
      ...DEFAULT_NAV,
      mainPanel: "review_domain",
    });
  });

  it("/review/sessions → all_conversations panel", () => {
    expect(parseUrl("/review/sessions")).toEqual({
      ...DEFAULT_NAV,
      mainPanel: "all_conversations",
    });
  });

  it("/extraction → extraction mode", () => {
    expect(parseUrl("/extraction")).toEqual({
      ...DEFAULT_NAV,
      appMode: "extraction",
    });
  });

  it("/extraction/conversation/:cid → extraction + conversation", () => {
    expect(parseUrl("/extraction/conversation/8")).toEqual({
      ...DEFAULT_NAV,
      appMode: "extraction",
      selectedConversationId: 8,
    });
  });

  it("unknown path → review default", () => {
    expect(parseUrl("/totally/unknown/path")).toEqual(DEFAULT_NAV);
  });

  it("NaN project id → selectedId null", () => {
    expect(parseUrl("/review/project/abc")).toEqual({
      ...DEFAULT_NAV,
      selectedId: null,
    });
  });

  it("negative project id → selectedId null", () => {
    expect(parseUrl("/review/project/-5")).toEqual({
      ...DEFAULT_NAV,
      selectedId: null,
    });
  });
});

// ── buildUrl ──────────────────────────────────────────────────────────────────

describe("buildUrl", () => {
  it("review default → /review", () => {
    expect(buildUrl(DEFAULT_NAV)).toBe("/review");
  });

  it("review + selectedId → /review/project/:pid", () => {
    expect(buildUrl({ ...DEFAULT_NAV, selectedId: 5 })).toBe("/review/project/5");
  });

  it("review + selectedId + cid → /review/project/:pid/conversation/:cid", () => {
    expect(buildUrl({ ...DEFAULT_NAV, selectedId: 5, selectedConversationId: 42 })).toBe(
      "/review/project/5/conversation/42",
    );
  });

  it("review + cid only → /review/conversation/:cid", () => {
    expect(buildUrl({ ...DEFAULT_NAV, selectedConversationId: 7 })).toBe("/review/conversation/7");
  });

  it("result_review → /review/rules", () => {
    expect(buildUrl({ ...DEFAULT_NAV, reviewMainTab: "result_review" })).toBe("/review/rules");
  });

  it("result_review + project → /review/rules/project/:pid", () => {
    expect(buildUrl({ ...DEFAULT_NAV, reviewMainTab: "result_review", selectedId: 3 })).toBe(
      "/review/rules/project/3",
    );
  });

  it("ingest → /review/ingest", () => {
    expect(buildUrl({ ...DEFAULT_NAV, mainPanel: "ingest" })).toBe("/review/ingest");
  });

  it("ingest + project → /review/ingest/project/:pid", () => {
    expect(buildUrl({ ...DEFAULT_NAV, mainPanel: "ingest", selectedId: 7 })).toBe(
      "/review/ingest/project/7",
    );
  });

  it("review_domain → /review/domain", () => {
    expect(buildUrl({ ...DEFAULT_NAV, mainPanel: "review_domain" })).toBe("/review/domain");
  });

  it("all_conversations → /review/sessions", () => {
    expect(buildUrl({ ...DEFAULT_NAV, mainPanel: "all_conversations" })).toBe("/review/sessions");
  });

  it("extraction → /extraction", () => {
    expect(buildUrl({ ...DEFAULT_NAV, appMode: "extraction" })).toBe("/extraction");
  });

  it("extraction + cid → /extraction/conversation/:cid", () => {
    expect(buildUrl({ ...DEFAULT_NAV, appMode: "extraction", selectedConversationId: 8 })).toBe(
      "/extraction/conversation/8",
    );
  });
});

// ── Roundtrip ─────────────────────────────────────────────────────────────────

describe("roundtrip: parseUrl(buildUrl(state)) === state", () => {
  const cases: NavState[] = [
    DEFAULT_NAV,
    { ...DEFAULT_NAV, selectedId: 5 },
    { ...DEFAULT_NAV, selectedId: 5, selectedConversationId: 42 },
    { ...DEFAULT_NAV, selectedConversationId: 7 },
    { ...DEFAULT_NAV, reviewMainTab: "result_review" },
    { ...DEFAULT_NAV, reviewMainTab: "result_review", selectedId: 3 },
    { ...DEFAULT_NAV, mainPanel: "ingest" },
    { ...DEFAULT_NAV, mainPanel: "ingest", selectedId: 7 },
    { ...DEFAULT_NAV, mainPanel: "review_domain" },
    { ...DEFAULT_NAV, mainPanel: "all_conversations" },
    { ...DEFAULT_NAV, appMode: "extraction" },
    { ...DEFAULT_NAV, appMode: "extraction", selectedConversationId: 8 },
  ];

  for (const state of cases) {
    it(`roundtrip for ${buildUrl(state)}`, () => {
      expect(parseUrl(buildUrl(state))).toEqual(state);
    });
  }
});
