import { useThemeStore } from "@/store/themeStore";

/**
 * 为 ECharts 生成随主题变化的渲染签名，主题切换时可安全重建图表实例。
 */
export function useChartThemeSignature(): string {
  return useThemeStore((state) => `${state.seedColor}-${state.isDark ? "dark" : "light"}`);
}
