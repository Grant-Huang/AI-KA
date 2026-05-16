/**
 * URL ↔ navigation state mapping.
 *
 * URL scheme:
 *   /review                                    project review (no selection)
 *   /review/project/:pid                       project review, project selected
 *   /review/project/:pid/conversation/:cid     project review + conversation
 *   /review/conversation/:cid                  project review, project-less conversation
 *   /review/rules                              pending rules
 *   /review/rules/project/:pid                 pending rules, project selected
 *   /review/ingest                             project init
 *   /review/ingest/project/:pid               project init, project selected
 *   /review/domain                             domain settings
 *   /review/sessions                           all sessions panel
 *   /extraction                                knowledge extraction
 *   /extraction/conversation/:cid              extraction + conversation
 */

export type AppMode = "review" | "extraction";
export type MainPanel = "analyze" | "ingest" | "review_domain" | "all_conversations";
export type ReviewTab = "analyze" | "result_review";

export interface NavState {
  appMode: AppMode;
  mainPanel: MainPanel;
  reviewMainTab: ReviewTab;
  selectedId: number | null;
  selectedConversationId: number | null;
}

export const DEFAULT_NAV: NavState = {
  appMode: "review",
  mainPanel: "analyze",
  reviewMainTab: "analyze",
  selectedId: null,
  selectedConversationId: null,
};

function toId(s: string | undefined): number | null {
  if (!s) return null;
  const n = parseInt(s, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function parseUrl(pathname: string): NavState {
  const parts = pathname.replace(/^\/+/, "").split("/").filter(Boolean);

  if (parts[0] === "extraction") {
    return {
      ...DEFAULT_NAV,
      appMode: "extraction",
      selectedConversationId: parts[1] === "conversation" ? toId(parts[2]) : null,
    };
  }

  if (parts[0] === "review" || parts.length === 0) {
    const seg = parts[1];

    if (!seg) return { ...DEFAULT_NAV };

    if (seg === "rules") {
      return {
        ...DEFAULT_NAV,
        reviewMainTab: "result_review",
        selectedId: parts[2] === "project" ? toId(parts[3]) : null,
      };
    }

    if (seg === "ingest") {
      return {
        ...DEFAULT_NAV,
        mainPanel: "ingest",
        selectedId: parts[2] === "project" ? toId(parts[3]) : null,
      };
    }

    if (seg === "domain") {
      return { ...DEFAULT_NAV, mainPanel: "review_domain" };
    }

    if (seg === "sessions") {
      return { ...DEFAULT_NAV, mainPanel: "all_conversations" };
    }

    if (seg === "conversation") {
      return { ...DEFAULT_NAV, selectedConversationId: toId(parts[2]) };
    }

    if (seg === "project") {
      const pid = toId(parts[2]);
      const cid = parts[3] === "conversation" ? toId(parts[4]) : null;
      return { ...DEFAULT_NAV, selectedId: pid, selectedConversationId: cid };
    }

    return { ...DEFAULT_NAV };
  }

  return { ...DEFAULT_NAV };
}

export function buildUrl(state: NavState): string {
  const { appMode, mainPanel, reviewMainTab, selectedId, selectedConversationId } = state;

  if (appMode === "extraction") {
    if (selectedConversationId != null) {
      return `/extraction/conversation/${selectedConversationId}`;
    }
    return "/extraction";
  }

  // review mode
  if (reviewMainTab === "result_review") {
    if (selectedId != null) return `/review/rules/project/${selectedId}`;
    return "/review/rules";
  }

  if (mainPanel === "ingest") {
    if (selectedId != null) return `/review/ingest/project/${selectedId}`;
    return "/review/ingest";
  }

  if (mainPanel === "review_domain") return "/review/domain";

  if (mainPanel === "all_conversations") return "/review/sessions";

  // mainPanel === "analyze"
  if (selectedId != null && selectedConversationId != null) {
    return `/review/project/${selectedId}/conversation/${selectedConversationId}`;
  }
  if (selectedId != null) return `/review/project/${selectedId}`;
  if (selectedConversationId != null) return `/review/conversation/${selectedConversationId}`;
  return "/review";
}
