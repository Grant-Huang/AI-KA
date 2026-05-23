import React from 'react';
import type { StreamState, ExtensionEvent } from '../../runtime';
import './MessageList.css';
export interface Message {
    id: string;
    role: 'user' | 'assistant';
    /** Final text content for completed turns. */
    content: string;
    timestamp?: string;
}
export interface MessageListProps {
    /** Completed conversation turns. */
    messages: Message[];
    /** Live streaming state from useSSEStream; omit when idle. */
    streaming?: StreamState;
    /** Called when artifact copy button is clicked. */
    onArtifactCopy?: (content: string) => void;
    /** Called when artifact download button is clicked. */
    onArtifactDownload?: (content: string) => void;
    /**
     * Called when user confirms a tool awaiting confirmation.
     * The app should send the approval to the backend via its own channel.
     */
    onToolConfirm?: (toolCallId: string) => void;
    /** Called when user cancels a tool awaiting confirmation. */
    onToolCancel?: (toolCallId: string) => void;
    /** Rendered when messages is empty and no streaming is active. */
    emptyState?: React.ReactNode;
    className?: string;
    /**
     * Render custom UI for extension events in arrival order.
     * Use this for domain-specific events that don't fit standard types.
     */
    renderExtension?: (event: ExtensionEvent) => React.ReactNode;
    /**
     * Sanitized HTML factory for Markdown rendering in assistant bubbles.
     * When provided, assistant bubbles render content as Markdown.
     * Must return sanitized HTML (e.g. marked + DOMPurify output).
     */
    renderMarkdown?: (source: string) => string;
    /**
     * Async Mermaid renderer passed to ArtifactPanel.
     * Receives source, returns SVG string. Called once streaming is done.
     */
    renderMermaid?: (source: string) => Promise<string>;
    /**
     * Syntax highlighter passed to ArtifactPanel.
     * Receives (code, lang), returns sanitized HTML. Called once streaming is done.
     */
    highlightCode?: (code: string, lang: string) => string;
}
export declare function MessageList({ messages, streaming, onArtifactCopy, onArtifactDownload, onToolConfirm, onToolCancel, emptyState, className, renderExtension, renderMarkdown, renderMermaid, highlightCode, }: MessageListProps): import("react/jsx-runtime").JSX.Element;
