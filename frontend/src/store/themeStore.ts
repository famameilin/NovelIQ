import { create } from "zustand";
import { persist } from "zustand/middleware";

export const DEFAULT_SEED = "#6366F1"; // Indigo 500
export const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

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
      // 中文注释：自动同步开启时，seedColor 属于任务上下文的派生结果，
      // 不应跨会话持久化到首页；只有手动主题模式才保留用户显式选择的颜色。
      partialize: (state) => ({
        isDark: state.isDark,
        autoSyncEnabled: state.autoSyncEnabled,
        ...(state.autoSyncEnabled ? {} : { seedColor: state.seedColor }),
      }),
    }
  )
);
