import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { useThemeStore, DEFAULT_SEED } from "@/store/themeStore";
import { useNovelStore } from "@/store/novelStore";
import { generateHomeThemePalette, generateThemePalette } from "@/lib/theme";
import { getDiagnosis } from "@/api/results";

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const STALE_TIME = 5 * 60 * 1000;
const HOME_ROUTE_SEED = "#FFFFFF";

/**
 * Applies the dynamic theme palette to :root CSS variables.
 * Auto-fetches theme_color from diagnosis API when novel/task changes.
 */
export function useNovelTheme() {
  const { seedColor, isDark, autoSyncEnabled, setSeedColor } = useThemeStore();
  const { currentNovelId, currentTaskId } = useNovelStore();
  const location = useLocation();
  const pathname = location.pathname;
  const urlTaskId = new URLSearchParams(location.search).get("task_id");
  const isThemePreviewRoute = pathname === "/dev/components";
  const isHomeRoute = pathname === "/";
  const isNovelRoute = pathname.startsWith("/novels/");
  const shouldUseNeutralTheme = isHomeRoute || (isNovelRoute && !urlTaskId);
  const diagnosisQuery = useQuery({
    queryKey: ["results", currentNovelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(currentNovelId!, currentTaskId!),
    enabled:
      (!!currentNovelId && !!currentTaskId) &&
      !shouldUseNeutralTheme &&
      (!isThemePreviewRoute || autoSyncEnabled),
    staleTime: STALE_TIME,
  });

  // 中文注释：主题色直接复用 diagnosis 的 React Query 缓存，
  // 避免页面和全局 hook 分别请求，造成重复取数与重复设色。
  useEffect(() => {
    // 中文注释：首页，以及未选择 task 的小说详情页，都应停留在白底预备态；
    // 这里直接忽略 store 里可能残留的旧 task，避免还没选任务就提前吃到旧主题色。
    if (shouldUseNeutralTheme) {
      if (seedColor !== HOME_ROUTE_SEED) {
        setSeedColor(HOME_ROUTE_SEED);
      }
      return;
    }

    // 中文注释：自动同步开关只服务于组件展示页的手动试色；
    // 正常业务页不应被这个临时开关卡住，否则一旦残留为 false，任务切换后主题色就不再更新。
    if (isThemePreviewRoute && !autoSyncEnabled) {
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
    isThemePreviewRoute,
    shouldUseNeutralTheme,
  ]);

  // Apply theme to CSS variables
  useEffect(() => {
    const palette = shouldUseNeutralTheme ? generateHomeThemePalette() : generateThemePalette(seedColor);
    const vars = isDark ? palette.dark : palette.light;
    const root = document.documentElement;

    Object.entries(vars).forEach(([key, value]) => {
      root.style.setProperty(key, value as string);
    });

    root.classList.toggle("dark", isDark);
  }, [seedColor, isDark, shouldUseNeutralTheme]);
}
