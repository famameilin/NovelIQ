import { create } from "zustand";
import { persist } from "zustand/middleware";

export const DEFAULT_SEED = "#6366F1"; // Indigo 500
export const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const THEME_STORE_VERSION = 2;

interface ThemeState {
  seedColor: string;
  isDark: boolean;
  autoSyncEnabled: boolean;
  setSeedColor: (hex: string) => void;
  toggleDark: () => void;
  setDark: (isDark: boolean) => void;
  setAutoSyncEnabled: (enabled: boolean) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      seedColor: DEFAULT_SEED,
      isDark: false,
      autoSyncEnabled: true,
      setSeedColor: (hex) => set({ seedColor: hex }),
      toggleDark: () => set((state) => ({ isDark: !state.isDark })),
      setDark: (isDark) => set({ isDark }),
      setAutoSyncEnabled: (enabled) => set({ autoSyncEnabled: enabled }),
    }),
    {
      name: "novel-viz-theme",
      version: THEME_STORE_VERSION,
      // 中文注释：自动同步开启时，seedColor 属于任务上下文的派生结果，
      // 不应跨会话持久化到首页；autoSyncEnabled 只用于组件展示页的临时试色，也不应持久化。
      // 只有组件展示页手动试色时，才保留用户显式选择的颜色。
      partialize: (state) => ({
        isDark: state.isDark,
        ...(state.autoSyncEnabled ? {} : { seedColor: state.seedColor }),
      }),
      migrate: (persistedState) => {
        const persistedThemeState = persistedState as Partial<ThemeState> | undefined;

        // 中文注释：旧版本 localStorage 里可能残留任务页派生的 seedColor，
        // 升级时要在自动同步模式下主动丢弃它，避免首页刷新后先被旧主题色 hydrate 回来。
        if (!persistedThemeState) {
          return persistedState;
        }

        if (persistedThemeState.autoSyncEnabled === false) {
          return {
            ...persistedThemeState,
            autoSyncEnabled: true,
          };
        }

        const { seedColor: _seedColor, ...restState } = persistedThemeState;
        return restState;
      },
    }
  )
);
