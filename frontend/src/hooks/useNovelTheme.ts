import { useEffect, useCallback } from "react";
import { useThemeStore } from "@/store/themeStore";
import { useNovelStore } from "@/store/novelStore";
import { generateThemePalette } from "@/lib/theme";
import { getDiagnosis } from "@/api/results";

const DEFAULT_SEED = "#6366F1";

/**
 * Applies the dynamic theme palette to :root CSS variables.
 * Auto-fetches theme_color from diagnosis API when novel/task changes.
 */
export function useNovelTheme() {
  const { seedColor, isDark, setSeedColor } = useThemeStore();
  const { currentNovelId, currentTaskId } = useNovelStore();

  // Fetch and apply theme color from diagnosis API
  const fetchAndApplyTheme = useCallback(async () => {
    if (!currentNovelId || !currentTaskId) {
      // No novel selected, use default
      setSeedColor(DEFAULT_SEED);
      return;
    }

    try {
      const diagnosis = await getDiagnosis(currentNovelId, currentTaskId);
      if (diagnosis?.theme_color) {
        setSeedColor(diagnosis.theme_color);
      } else {
        setSeedColor(DEFAULT_SEED);
      }
    } catch (e) {
      console.warn("Failed to fetch theme color:", e);
      setSeedColor(DEFAULT_SEED);
    }
  }, [currentNovelId, currentTaskId, setSeedColor]);

  // Fetch theme when novel/task changes
  useEffect(() => {
    fetchAndApplyTheme();
  }, [fetchAndApplyTheme]);

  // Apply theme to CSS variables
  useEffect(() => {
    const palette = generateThemePalette(seedColor);
    const vars = isDark ? palette.dark : palette.light;
    const root = document.documentElement;

    Object.entries(vars).forEach(([key, value]) => {
      root.style.setProperty(key, value as string);
    });

    root.classList.toggle("dark", isDark);
  }, [seedColor, isDark]);
}