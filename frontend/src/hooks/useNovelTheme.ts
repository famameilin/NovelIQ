import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useThemeStore, DEFAULT_SEED } from "@/store/themeStore";
import { useNovelStore } from "@/store/novelStore";
import { generateThemePalette } from "@/lib/theme";
import { getDiagnosis } from "@/api/results";

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const STALE_TIME = 5 * 60 * 1000;

/**
 * Applies the dynamic theme palette to :root CSS variables.
 * Auto-fetches theme_color from diagnosis API when novel/task changes.
 */
export function useNovelTheme() {
  const { seedColor, isDark, autoSyncEnabled, setSeedColor } = useThemeStore();
  const { currentNovelId, currentTaskId } = useNovelStore();
  const diagnosisQuery = useQuery({
    queryKey: ["results", currentNovelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(currentNovelId!, currentTaskId!),
    enabled: autoSyncEnabled && !!currentNovelId && !!currentTaskId,
    staleTime: STALE_TIME,
  });

  // 中文注释：主题色直接复用 diagnosis 的 React Query 缓存，
  // 避免页面和全局 hook 分别请求，造成重复取数与重复设色。
  useEffect(() => {
    if (!autoSyncEnabled) {
      return;
    }

    if (!currentNovelId || !currentTaskId) {
      if (seedColor !== DEFAULT_SEED) {
        setSeedColor(DEFAULT_SEED);
      }
      return;
    }

    const themeColor = diagnosisQuery.data?.theme_color;
    if (themeColor && HEX_COLOR_RE.test(themeColor)) {
      if (themeColor !== seedColor) {
        setSeedColor(themeColor);
      }
      return;
    }

    if (diagnosisQuery.isFetched && seedColor !== DEFAULT_SEED) {
      if (diagnosisQuery.isError) {
        console.warn("Failed to fetch theme color:", diagnosisQuery.error);
      }
      setSeedColor(DEFAULT_SEED);
    }
  }, [
    currentNovelId,
    currentTaskId,
    diagnosisQuery.data?.theme_color,
    diagnosisQuery.error,
    diagnosisQuery.isError,
    diagnosisQuery.isFetched,
    autoSyncEnabled,
    seedColor,
    setSeedColor,
  ]);

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
