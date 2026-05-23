import './ArtifactPanel.css';
export type ArtifactType = 'code' | 'html' | 'mermaid' | 'markdown' | 'table';
export interface ArtifactPanelProps {
    type: ArtifactType;
    content: string;
    language?: string;
    /** Whether content is still streaming in */
    streaming?: boolean;
    /** Called when user clicks the copy button */
    onCopy?: (content: string) => void;
    /** Called when user clicks download. If not provided, default browser download is triggered. */
    onDownload?: (content: string) => void;
    /**
     * Async Mermaid renderer. Receives the source string, returns an SVG string.
     * Called once streaming is complete. If absent, a placeholder is shown.
     */
    renderMermaid?: (source: string) => Promise<string>;
    /**
     * Syntax highlighter. Receives (code, lang), returns an HTML string.
     * Called once streaming is complete. Falls back to plain text if absent.
     * Must return sanitized HTML.
     */
    highlightCode?: (code: string, lang: string) => string;
    /**
     * Markdown renderer. Used when type='markdown'.
     * Must return sanitized HTML.
     */
    renderMarkdown?: (source: string) => string;
}
export declare function ArtifactPanel({ type, content, language, streaming, onCopy, onDownload, renderMermaid, highlightCode, renderMarkdown, }: ArtifactPanelProps): import("react/jsx-runtime").JSX.Element;
