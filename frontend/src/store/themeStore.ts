import { create } from "zustand";
import { persist } from "zustand/middleware";

const DEFAULT_SEED = "#6366F1"; // Indigo 500

interface ThemeState {
  seedColor: string;
  isDark: boolean;
  setSeedColor: (hex: string) => void;
  toggleDark: () => void;
  setDark: (isDark: boolean) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      seedColor: DEFAULT_SEED,
      isDark: false,
      setSeedColor: (hex) => set({ seedColor: hex }),
      toggleDark: () => set((state) => ({ isDark: !state.isDark })),
      setDark: (isDark) => set({ isDark }),
    }),
    { name: "novel-viz-theme" }
  )
);
