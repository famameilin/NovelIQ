export type MetricAccent =
  | "primary"
  | "chart-1"
  | "chart-2"
  | "chart-3"
  | "chart-4"
  | "chart-5";

export const METRIC_ACCENT_CARD_CLASS_MAP: Record<MetricAccent, string> = {
  primary: "bg-gradient-to-br from-surface via-surface to-primary/15 hover:border-primary/30",
  "chart-1": "bg-gradient-to-br from-surface via-surface to-chart-1/15 hover:border-chart-1/30",
  "chart-2": "bg-gradient-to-br from-surface via-surface to-chart-2/15 hover:border-chart-2/30",
  "chart-3": "bg-gradient-to-br from-surface via-surface to-chart-3/15 hover:border-chart-3/30",
  "chart-4": "bg-gradient-to-br from-surface via-surface to-chart-4/15 hover:border-chart-4/30",
  "chart-5": "bg-gradient-to-br from-surface via-surface to-chart-5/15 hover:border-chart-5/30",
};

export const METRIC_ACCENT_BAR_CLASS_MAP: Record<MetricAccent, string> = {
  primary: "bg-primary",
  "chart-1": "bg-chart-1",
  "chart-2": "bg-chart-2",
  "chart-3": "bg-chart-3",
  "chart-4": "bg-chart-4",
  "chart-5": "bg-chart-5",
};

export function getMetricAccentColor(accent: MetricAccent, alpha?: number): string {
  return alpha == null ? `hsl(var(--${accent}))` : `hsl(var(--${accent}) / ${alpha})`;
}

export function getMetricAccentHoverTextClass(accent: MetricAccent): string {
  const map: Record<MetricAccent, string> = {
    primary: "hover:text-primary",
    "chart-1": "hover:text-chart-1",
    "chart-2": "hover:text-chart-2",
    "chart-3": "hover:text-chart-3",
    "chart-4": "hover:text-chart-4",
    "chart-5": "hover:text-chart-5",
  };
  return map[accent];
}
