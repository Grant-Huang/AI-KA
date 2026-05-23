import './ThinkBlock.css';
export interface ThinkBlockProps {
    /** Accumulated think content */
    content: string;
    /** Whether the stream is still active (not done yet) */
    streaming?: boolean;
    /** When streaming ends and done=true, auto-collapse after this delay (ms). Default 1500. */
    autoCollapseDelay?: number;
}
export declare function ThinkBlock({ content, streaming, autoCollapseDelay }: ThinkBlockProps): import("react/jsx-runtime").JSX.Element;
