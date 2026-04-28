import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { useThemeStore, DEFAULT_SEED } from "@/store/themeStore";
import { useNovelStore } from "@/store/novelStore";
import { generateHomeThemePalette, generateThemePalette } from "@/lib/theme";
import { getDiagnosis } from "@/api/results";
import { getTaskStatus } from "@/api/analysis";

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const STALE_TIME = 5 * 60 * 1000;

/**
 * 修改原因: 首页白底预备态不应污染业务页 seedColor，组件展示页也不应在首屏先吃到任务主题。
 *
 * 修改原因: 新建任务的诊断结果尚未生成时，不能用 DEFAULT_SEED 推导业务页背景色，
 * 否则分析进度页会先切到紫色底；只在拿到有效 theme_color 后才进入任务主题。
 *
 * Applies the dynamic theme palette to :root CSS variables.
 * Auto-fetches theme_color from diagnosis API when novel/task changes.
 */
export function useNovelTheme() {
  const { seedColor, isDark, setSeedColor } = useThemeStore();
  const { currentNovelId, currentTaskId } = useNovelStore();
  const location = useLocation();
  const pathname = location.pathname;
  const urlTaskId = new URLSearchParams(location.search).get("task_id");
  const isThemePreviewRoute = pathname === "/dev/components";
  const isHomeRoute = pathname === "/";
  const isNovelRoute = pathname.startsWith("/novels/");
  const shouldUseNeutralTheme = isHomeRoute || (isNovelRoute && !urlTaskId);
  const currentTaskThemeKey =
    currentNovelId && currentTaskId ? `${currentNovelId}:${currentTaskId}` : null;
  const taskStatusQuery = useQuery({
    queryKey: ["task-status", currentNovelId, currentTaskId],
    queryFn: () => getTaskStatus(currentNovelId!, currentTaskId!),
    enabled: !!currentTaskThemeKey && !shouldUseNeutralTheme && !isThemePreviewRoute,
    staleTime: 5 * 1000,
  });
  const taskStatus = taskStatusQuery.data?.status;
  const isTaskActivelyProcessing =
    taskStatus === "pending" || taskStatus === "running" || taskStatus === "cancelling";
  const diagnosisQuery = useQuery({
    queryKey: ["results", currentNovelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(currentNovelId!, currentTaskId!),
    enabled:
      !!currentTaskThemeKey &&
      !shouldUseNeutralTheme &&
      !isThemePreviewRoute &&
      taskStatusQuery.isSuccess &&
      !isTaskActivelyProcessing,
    staleTime: STALE_TIME,
  });
  const themeColor = diagnosisQuery.data?.theme_color;
  const hasValidThemeColor = !!themeColor && HEX_COLOR_RE.test(themeColor);
  const shouldUsePendingTaskTheme =
    !!currentTaskThemeKey &&
    !shouldUseNeutralTheme &&
    !isThemePreviewRoute &&
    (!taskStatusQuery.isSuccess || isTaskActivelyProcessing || !hasValidThemeColor);
  const effectiveSeedColor = hasValidThemeColor ? themeColor : DEFAULT_SEED;
  const shouldUseNeutralPalette = shouldUseNeutralTheme || shouldUsePendingTaskTheme;

  // 主题色直接复用 diagnosis 的 React Query 缓存，
  // 避免页面和全局 hook 分别请求，造成重复取数与重复设色。
  useEffect(() => {
    // 首页，以及未选择 task 的小说详情页，都应停留在白底预备态；
    // 这里不再把白底态写回 store，避免离开 neutral route 时先闪出白色 seed 推导出来的临时主题。
    if (shouldUseNeutralTheme) {
      return;
    }

    // 组件展示页完全隔离任务主题同步，
    // 首屏也不能先请求 diagnosis 或把上一个任务主题写回来。
    if (isThemePreviewRoute) {
      return;
    }

    if (!currentTaskThemeKey) {
      if (seedColor !== DEFAULT_SEED) {
        setSeedColor(DEFAULT_SEED);
      }
      return;
    }

    // 运行中的任务还没有稳定 diagnosis，主题 hook 不能抢先打结果接口；
    // 此时统一保持 neutral palette，并清掉旧 seed，避免沿用上一个任务主题。
    if (!taskStatusQuery.isSuccess || isTaskActivelyProcessing) {
      if (seedColor !== DEFAULT_SEED) {
        setSeedColor(DEFAULT_SEED);
      }
      return;
    }

    if (hasValidThemeColor) {
      if (themeColor !== seedColor) {
        setSeedColor(themeColor);
      }
      return;
    }

    // 当新 task 的 diagnosis 还没回来或暂时报错时，页面保持 neutral palette；
    // 这里只清掉旧 seed，不把 task 标记为已解析，避免 DEFAULT_SEED 推出紫色业务页背景。
    if (diagnosisQuery.isFetched && seedColor !== DEFAULT_SEED) {
      if (diagnosisQuery.isError) {
        console.warn("Failed to fetch theme color:", diagnosisQuery.error);
      }
      setSeedColor(DEFAULT_SEED);
      return;
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
    taskStatusQuery.isSuccess,
    isTaskActivelyProcessing,
    isThemePreviewRoute,
    shouldUseNeutralTheme,
  ]);

  // Apply theme to CSS variables
  useEffect(() => {
    const palette = shouldUseNeutralPalette
      ? generateHomeThemePalette()
      : generateThemePalette(isThemePreviewRoute ? seedColor : effectiveSeedColor);
    const vars = isDark ? palette.dark : palette.light;
    const root = document.documentElement;

    Object.entries(vars).forEach(([key, value]) => {
      root.style.setProperty(key, value as string);
    });

    root.classList.toggle("dark", isDark);
  }, [effectiveSeedColor, isDark, isThemePreviewRoute, seedColor, shouldUseNeutralPalette]);
}
