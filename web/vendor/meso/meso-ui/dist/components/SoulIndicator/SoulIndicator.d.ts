import type { SoulPayload } from '../../runtime';
import './SoulIndicator.css';
export interface SoulIndicatorProps {
    soul: SoulPayload;
    /** Compact mode: only show avatar, no name or traits. */
    compact?: boolean;
}
export declare function SoulIndicator({ soul, compact }: SoulIndicatorProps): import("react/jsx-runtime").JSX.Element;
