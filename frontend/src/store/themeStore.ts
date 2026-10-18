import { create } from "zustand";
import { persist } from "zustand/middleware";

export const DEFAULT_SEED = "#6366F1"; // Indigo 500 基准色
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
      // 只持久化当前状态需要的字段：开启自动同步时 seedColor 属于任务派生结果，不持久化；
      // 关闭自动同步时保留组件展示页手动试色选择的颜色；autoSyncEnabled 不持久化
      partialize: (state) => ({
        isDark: state.isDark,
        ...(state.autoSyncEnabled ? {} : { seedColor: state.seedColor }),
      }),
    }
  )
);
