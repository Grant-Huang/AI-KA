import './ChatBubble.css';
export type ChatRole = 'user' | 'assistant';
export interface ChatBubbleProps {
    role: ChatRole;
    /** Text content */
    content: string;
    /** Show streaming cursor at end */
    streaming?: boolean;
    /** Timestamp label */
    timestamp?: string;
    /**
     * When true, render content as Markdown via renderMarkdown.
     * Falls back to line-split if renderMarkdown is not provided.
     */
    markdown?: boolean;
    /**
     * Sanitized HTML string factory (e.g. marked + DOMPurify).
     * Required for markdown=true to take effect.
     */
    renderMarkdown?: (source: string) => string;
}
export declare function ChatBubble({ role, content, streaming, timestamp, markdown, renderMarkdown, }: ChatBubbleProps): import("react/jsx-runtime").JSX.Element;
