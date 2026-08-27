import type { EmotionTrendWindow } from "@/api/types";

export type EmotionTrendSeriesKey =
  | "pooled_pos_density"
  | "pooled_neg_density"
  | "pooled_net_density"
  | "smoothed_pooled_net_density";

export interface EmotionTrendSeriesConfig {
  key: EmotionTrendSeriesKey;
  smoothedKey: keyof EmotionTrendWindow;
  name: string;
  colorVar: "--chart-positive" | "--chart-negative" | "--chart-1" | "--primary";
  role: "aux" | "support" | "main";
  useSmoothed: boolean;
}

export const EMOTION_TREND_SERIES_CONFIG: readonly EmotionTrendSeriesConfig[] = [
  {
    key: "pooled_pos_density",
    smoothedKey: "smoothed_pooled_pos_density",
    name: "正向强度",
    colorVar: "--chart-positive",
    role: "aux",
    useSmoothed: true,
  },
  {
    key: "pooled_neg_density",
    smoothedKey: "smoothed_pooled_neg_density",
    name: "负向强度",
    colorVar: "--chart-negative",
    role: "aux",
    useSmoothed: true,
  },
  {
    key: "pooled_net_density",
    smoothedKey: "pooled_net_density",
    name: "原始趋势",
    colorVar: "--chart-1",
    role: "support",
    useSmoothed: false,
  },
  {
    key: "smoothed_pooled_net_density",
    smoothedKey: "smoothed_pooled_net_density",
    name: "平滑趋势",
    colorVar: "--primary",
    role: "main",
    useSmoothed: true,
  },
] as const;

/** 2026-08-16 读取情绪窗口系列值，保证概览预览与完整曲线使用相同的后端口径 */
export function getEmotionTrendSeriesValue(
  window: EmotionTrendWindow,
  config: EmotionTrendSeriesConfig,
): number | null {
  const rawValue = window[config.key];
  const smoothedValue = window[config.smoothedKey] as number | null;
  return config.useSmoothed ? smoothedValue ?? rawValue : rawValue;
}

/** 2026-08-16 格式化 ECharts tooltip 的数值，兼容 value 为坐标数组的返回形态 */
export function formatEmotionTrendTooltipValue(value: unknown): string {
  const numericValue = Array.isArray(value) ? value[1] : value;
  return typeof numericValue === "number" && Number.isFinite(numericValue)
    ? numericValue.toFixed(4)
    : "-";
}
