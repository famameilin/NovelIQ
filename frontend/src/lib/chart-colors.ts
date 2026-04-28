/**
 * chart-colors - 通用图表配色常量
 *
 * 所有 ECharts 图表共享的 CSS 变量色板，通过 getCSSColorVar() 运行时解析，
 * 遵循 §4.8 规范：禁止硬编码十六进制颜色值
 */

/** 图表配色（CSS 变量名），所有 ECharts 图表共享 */
export const CHART_COLORS = [
  "--chart-1",
  "--chart-2",
  "--chart-3",
  "--chart-4",
  "--chart-5",
  "--chart-6",
  "--chart-7",
  "--chart-8",
] as const;
