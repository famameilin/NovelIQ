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
      // 2026-04-30: 本地 version 迁移清理
      // 任务：theme store latest-only 收口
      // 说明：只保留当前状态真正需要的持久化字段，不再兼容旧版本 migrate/version 分支
      // 自动同步开启时，seedColor 属于任务上下文的派生结果，
      // 不应跨会话持久化到首页；autoSyncEnabled 只用于组件展示页的临时试色，也不应持久化
      // 只有组件展示页手动试色时，才保留用户显式选择的颜色
      partialize: (state) => ({
        isDark: state.isDark,
        ...(state.autoSyncEnabled ? {} : { seedColor: state.seedColor }),
      }),
    }
  )
);
