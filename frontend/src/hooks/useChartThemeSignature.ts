import { useThemeStore } from "@/store/themeStore";

/**
 * 修改时间: 2026-04-21
 * 任务: fix-novel-theme-runtime-crash
 * 说明: 为 ECharts 生成随主题变化的渲染签名，主题切换时可安全重建图表实例。
 */
export function useChartThemeSignature(): string {
  return useThemeStore((state) => `${state.seedColor}-${state.isDark ? "dark" : "light"}`);
}
