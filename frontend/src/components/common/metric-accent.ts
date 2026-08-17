export type MetricAccent =
  | "primary"
  | "chart-1"
  | "chart-2"
  | "chart-3"
  | "chart-4"
  | "chart-5";

export type MetricTone = "objective" | "subjective";

export const METRIC_TONE_CLASS_MAP: Record<MetricTone, string> = {
  objective: "border-l-2 border-l-current",
  subjective: "border-dashed",
};

const CARD_ACCENT_ALIAS: Record<MetricAccent, "primary" | "chart-2"> = {
  primary: "primary",
  "chart-1": "primary",
  "chart-2": "chart-2",
  "chart-3": "chart-2",
  "chart-4": "primary",
  "chart-5": "chart-2",
};

/** 2026-08-16 将所有卡片强调色收敛到两种实际视觉分支 */
export function resolveCardAccent(accent: MetricAccent): "primary" | "chart-2" {
  return CARD_ACCENT_ALIAS[accent];
}

export const METRIC_ACCENT_CARD_CLASS_MAP: Record<MetricAccent, string> = {
  primary: "bg-gradient-to-br from-surface via-surface to-primary/15 hover:border-primary/30",
  "chart-1": "bg-gradient-to-br from-surface via-surface to-primary/15 hover:border-primary/30",
  "chart-2": "bg-gradient-to-br from-surface via-surface to-chart-2/15 hover:border-chart-2/30",
  "chart-3": "bg-gradient-to-br from-surface via-surface to-chart-2/15 hover:border-chart-2/30",
  "chart-4": "bg-gradient-to-br from-surface via-surface to-primary/15 hover:border-primary/30",
  "chart-5": "bg-gradient-to-br from-surface via-surface to-chart-2/15 hover:border-chart-2/30",
};

export const METRIC_ACCENT_BAR_CLASS_MAP: Record<MetricAccent, string> = {
  primary: "bg-primary",
  "chart-1": "bg-primary",
  "chart-2": "bg-chart-2",
  "chart-3": "bg-chart-2",
  "chart-4": "bg-primary",
  "chart-5": "bg-chart-2",
};

export function getMetricAccentColor(accent: MetricAccent, alpha?: number): string {
  const resolvedAccent = resolveCardAccent(accent);
  return alpha == null
    ? `hsl(var(--${resolvedAccent}))`
    : `hsl(var(--${resolvedAccent}) / ${alpha})`;
}

export function getMetricAccentHoverTextClass(accent: MetricAccent): string {
  const map: Record<"primary" | "chart-2", string> = {
    primary: "hover:text-primary",
    "chart-2": "hover:text-chart-2",
  };
  return map[resolveCardAccent(accent)];
}
