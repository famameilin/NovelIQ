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
    { name: "novel-viz-theme" }
  )
);
