import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { useThemeStore, DEFAULT_SEED } from "@/store/themeStore";
import { useNovelStore } from "@/store/novelStore";
import { generateHomeThemePalette, generateThemePalette } from "@/lib/theme";
import { getDiagnosis } from "@/api/results";

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const STALE_TIME = 5 * 60 * 1000;

/**
 * 修改时间: 2026-04-22
 * 任务: 修复主题色路由切换闪动与组件展示页串色
 * 修改原因: 首页白底预备态不应污染业务页 seedColor，组件展示页也不应在首屏先吃到任务主题。
 *
 * Applies the dynamic theme palette to :root CSS variables.
 * Auto-fetches theme_color from diagnosis API when novel/task changes.
 */
export function useNovelTheme() {
  const { seedColor, isDark, setSeedColor } = useThemeStore();
  const { currentNovelId, currentTaskId } = useNovelStore();
  const location = useLocation();
  const resolvedTaskThemeKeyRef = useRef<string | null>(null);
  const pathname = location.pathname;
  const urlTaskId = new URLSearchParams(location.search).get("task_id");
  const isThemePreviewRoute = pathname === "/dev/components";
  const isHomeRoute = pathname === "/";
  const isNovelRoute = pathname.startsWith("/novels/");
  const shouldUseNeutralTheme = isHomeRoute || (isNovelRoute && !urlTaskId);
  const currentTaskThemeKey =
    currentNovelId && currentTaskId ? `${currentNovelId}:${currentTaskId}` : null;
  const diagnosisQuery = useQuery({
    queryKey: ["results", currentNovelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(currentNovelId!, currentTaskId!),
    enabled: !!currentTaskThemeKey && !shouldUseNeutralTheme && !isThemePreviewRoute,
    staleTime: STALE_TIME,
  });
  const themeColor = diagnosisQuery.data?.theme_color;
  const hasValidThemeColor = !!themeColor && HEX_COLOR_RE.test(themeColor);
  const effectiveSeedColor =
    hasValidThemeColor
      ? themeColor
      : currentTaskThemeKey && resolvedTaskThemeKeyRef.current === currentTaskThemeKey
        ? seedColor
        : DEFAULT_SEED;

  // 中文注释：主题色直接复用 diagnosis 的 React Query 缓存，
  // 避免页面和全局 hook 分别请求，造成重复取数与重复设色。
  useEffect(() => {
    // 中文注释：首页，以及未选择 task 的小说详情页，都应停留在白底预备态；
    // 这里不再把白底态写回 store，避免离开 neutral route 时先闪出白色 seed 推导出来的临时主题。
    if (shouldUseNeutralTheme) {
      return;
    }

    // 中文注释：组件展示页完全隔离任务主题同步，
    // 首屏也不能先请求 diagnosis 或把上一个任务主题写回来。
    if (isThemePreviewRoute) {
      return;
    }

    if (!currentTaskThemeKey) {
      resolvedTaskThemeKeyRef.current = null;
      if (seedColor !== DEFAULT_SEED) {
        setSeedColor(DEFAULT_SEED);
      }
      return;
    }

    if (hasValidThemeColor) {
      resolvedTaskThemeKeyRef.current = currentTaskThemeKey;
      if (themeColor !== seedColor) {
        setSeedColor(themeColor);
      }
      return;
    }

    // 中文注释：当新 task 的 diagnosis 还没回来时，palette effect 会先回退到 DEFAULT_SEED，
    // 这里只在请求落定后再把 store 标记为“已解析”，避免旧 task / neutral seed 串到新任务页。
    if (diagnosisQuery.isFetched && seedColor !== DEFAULT_SEED) {
      if (diagnosisQuery.isError) {
        console.warn("Failed to fetch theme color:", diagnosisQuery.error);
      }
      resolvedTaskThemeKeyRef.current = currentTaskThemeKey;
      setSeedColor(DEFAULT_SEED);
      return;
    }

    if (diagnosisQuery.isFetched) {
      resolvedTaskThemeKeyRef.current = currentTaskThemeKey;
    }
  }, [
    currentTaskThemeKey,
    diagnosisQuery.error,
    diagnosisQuery.isError,
    diagnosisQuery.isFetched,
    hasValidThemeColor,
    themeColor,
    seedColor,
    setSeedColor,
    isThemePreviewRoute,
    shouldUseNeutralTheme,
  ]);

  // Apply theme to CSS variables
  useEffect(() => {
    const palette = shouldUseNeutralTheme
      ? generateHomeThemePalette()
      : generateThemePalette(isThemePreviewRoute ? seedColor : effectiveSeedColor);
    const vars = isDark ? palette.dark : palette.light;
    const root = document.documentElement;

    Object.entries(vars).forEach(([key, value]) => {
      root.style.setProperty(key, value as string);
    });

    root.classList.toggle("dark", isDark);
  }, [effectiveSeedColor, isDark, isThemePreviewRoute, seedColor, shouldUseNeutralTheme]);
}
