import { useEffect } from "react";
import { useThemeStore, DEFAULT_SEED } from "@/store/themeStore";
import { useNovelStore } from "@/store/novelStore";
import { generateThemePalette } from "@/lib/theme";
import { getDiagnosis } from "@/api/results";

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

/**
 * Applies the dynamic theme palette to :root CSS variables.
 * Auto-fetches theme_color from diagnosis API when novel/task changes.
 */
export function useNovelTheme() {
  const { seedColor, isDark, setSeedColor } = useThemeStore();
  const { currentNovelId, currentTaskId } = useNovelStore();

  // Fetch theme when novel/task changes
  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      if (!currentNovelId || !currentTaskId) {
        setSeedColor(DEFAULT_SEED);
        return;
      }

      try {
        const diagnosis = await getDiagnosis(currentNovelId, currentTaskId);
        if (!cancelled) {
          setSeedColor(
            diagnosis?.theme_color && HEX_COLOR_RE.test(diagnosis.theme_color)
              ? diagnosis.theme_color
              : DEFAULT_SEED
          );
        }
      } catch (e) {
        if (!cancelled) {
          console.warn("Failed to fetch theme color:", e);
          setSeedColor(DEFAULT_SEED);
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [currentNovelId, currentTaskId, setSeedColor]);

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
