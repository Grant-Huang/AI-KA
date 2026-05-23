import React from 'react';
import './ThreeColumnLayout.css';
export interface NavItem {
    id: string;
    label: string;
    icon: React.ReactNode;
    active?: boolean;
    onClick?: () => void;
}
export interface ThreeColumnLayoutProps {
    /** Nav items for the left sidebar */
    navItems?: NavItem[];
    /** Content for the bottom of the sidebar (e.g. user avatar/menu) */
    sidebarFooter?: React.ReactNode;
    /** Full content of the middle session column */
    sessionColumn?: React.ReactNode;
    /** Whether the session column is visible */
    sessionColumnVisible?: boolean;
    /** Main area content (chat pane) */
    children: React.ReactNode;
    /** Whether sidebar starts collapsed */
    defaultCollapsed?: boolean;
    /** App name shown in sidebar header */
    appName?: string;
    /** Optional header content for the main area */
    mainHeader?: React.ReactNode;
    /** Content rendered in the artifact pane (right side of split layout) */
    artifactContent?: React.ReactNode;
    /** Whether to show the split layout */
    splitMode?: boolean;
    /** Callback when splitMode changes (e.g. user collapses artifact pane) */
    onSplitModeChange?: (split: boolean) => void;
    /** Initial chat/artifact split ratio (0.4–0.8), default 0.6 */
    defaultSplitRatio?: number;
    /** Callback when ratio changes after drag */
    onSplitRatioChange?: (ratio: number) => void;
    /** localStorage key to persist split ratio; omit to skip persistence */
    splitRatioStorageKey?: string;
}
export declare function ThreeColumnLayout({ navItems, sidebarFooter, sessionColumn, sessionColumnVisible, children, defaultCollapsed, appName, mainHeader, artifactContent, splitMode, onSplitModeChange, defaultSplitRatio, onSplitRatioChange, splitRatioStorageKey, }: ThreeColumnLayoutProps): import("react/jsx-runtime").JSX.Element;
