export type Theme = 'light' | 'dark';
export declare function useTheme(): {
    theme: Theme;
    toggle: () => void;
};
