import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatNumber, formatPercent } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export type MetricFormat = "number" | "percent" | "score" | "raw";

/** 指标卡片的强调色，映射到 chart-* CSS 变量体系 */
export type MetricAccent =
  | "primary"
  | "chart-1"
  | "chart-2"
  | "chart-3"
  | "chart-4"
  | "chart-5";

export interface MetricCardProps {
  label: string;
  value: number;
  format?: MetricFormat;
  maxScore?: number;
  decimals?: number;
  icon?: ReactNode;
  description?: string;
  className?: string;
  /** @default "primary" */
  accent?: MetricAccent;
  /** 右上角趋势标签，如 "+12%" */
  trend?: string;
  /** 底部插槽（如头像堆叠） */
  footer?: ReactNode;
  /** 右上角装饰模糊光斑 */
  showOrb?: boolean;
  /** 强制显示进度条。默认 score/percent 自动显示；number/raw 下需手动开启 */
  showBar?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Accent → static Tailwind classes                                   */
/* ------------------------------------------------------------------ */

/**
 * Every class string is written literally so Tailwind can scan & generate it.
 * Dynamic interpolation like `from-${accent}` does NOT work with Tailwind v4.
 */
const ACCENT_MAP: Record<
  MetricAccent,
  {
    /** Card gradient + hover border (applied via className on the Card) */
    card: string;
    /** Progress bar gradient */
    bar: string;
  }
> = {
  primary: {
    card:
      "bg-gradient-to-br from-surface via-surface to-primary/15 " +
      "hover:border-primary/30",
    bar: "bg-gradient-to-r from-primary to-primary-hover",
  },
  "chart-1": {
    card:
      "bg-gradient-to-br from-surface via-surface to-chart-1/15 " +
      "hover:border-chart-1/30",
    bar: "bg-gradient-to-r from-chart-1 to-chart-2",
  },
  "chart-2": {
    card:
      "bg-gradient-to-br from-surface via-surface to-chart-2/15 " +
      "hover:border-chart-2/30",
    bar: "bg-gradient-to-r from-chart-2 to-chart-3",
  },
  "chart-3": {
    card:
      "bg-gradient-to-br from-surface via-surface to-chart-3/15 " +
      "hover:border-chart-3/30",
    bar: "bg-gradient-to-r from-chart-3 to-chart-4",
  },
  "chart-4": {
    card:
      "bg-gradient-to-br from-surface via-surface to-chart-4/15 " +
      "hover:border-chart-4/30",
    bar: "bg-gradient-to-r from-chart-4 to-chart-5",
  },
  "chart-5": {
    card:
      "bg-gradient-to-br from-surface via-surface to-chart-5/15 " +
      "hover:border-chart-5/30",
    bar: "bg-gradient-to-r from-chart-5 to-chart-1",
  },
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function formatValue(
  value: number,
  format: MetricFormat,
  decimals: number,
  maxScore: number,
): string {
  switch (format) {
    case "percent":
      return formatPercent(value, decimals);
    case "score":
      return `${formatNumber(value, decimals)}/${maxScore}`;
    case "number":
      return formatNumber(value, decimals);
    case "raw":
    default:
      return String(value);
  }
}

function barWidth(format: MetricFormat, value: number, maxScore: number): number {
  if (format === "score") return Math.min(value / maxScore, 1) * 100;
  if (format === "percent") return Math.min(value, 1) * 100;
  return 0;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function MetricCard({
  label,
  value,
  format = "number",
  maxScore = 5,
  decimals = 1,
  icon,
  description,
  className,
  accent = "primary",
  trend,
  footer,
  showOrb = false,
  showBar: forceBar = false,
}: MetricCardProps) {
  const displayValue = formatValue(value, format, decimals, maxScore);
  const autoBar = format === "score" || format === "percent";
  const showBar = autoBar || forceBar;
  const fillPct = autoBar ? barWidth(format, value, maxScore) : Math.min(value, 100);
  const { card: accentCard, bar: barGradient } = ACCENT_MAP[accent];

  const content = (
    <Card
      variant="elevated"
      className={cn(accentCard, "relative rounded-xl p-5", className)}
    >
      {/* Decorative orb */}
      {showOrb && (
        <div
          className={cn(
            "pointer-events-none absolute h-24 w-24 rounded-full blur-2xl",
            accent === "primary" ? "-right-4 -top-4" : "-bottom-6 -right-6 h-20 w-20",
          )}
          style={{ backgroundColor: `hsl(var(--${accent}) / 0.05)` }}
        />
      )}

      {/* Header row */}
      <div className={cn(showOrb && "relative flex items-start justify-between")}>
        <div className="flex items-center gap-3">
          {/* Icon with tinted background */}
          {icon && (
            <div
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
              style={{
                backgroundColor: `hsl(var(--${accent}) / 0.1)`,
                color: `hsl(var(--${accent}))`,
              }}
            >
              {icon}
            </div>
          )}
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
              {label}
            </p>
            <p className="mt-0.5 text-2xl font-bold tabular-nums text-text">
              {displayValue}
            </p>
          </div>
        </div>

        {/* Trend badge */}
        {trend && (
          <div
            className="flex h-8 items-center gap-1 rounded-full px-3 text-xs font-medium"
            style={{
              backgroundColor: `hsl(var(--${accent}) / 0.1)`,
              color: `hsl(var(--${accent}))`,
            }}
          >
            {trend}
          </div>
        )}
      </div>

      {/* Progress bar */}
      {showBar && (
        <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-border">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              barGradient,
            )}
            style={{ width: `${fillPct}%` }}
          />
        </div>
      )}

      {/* Footer slot (e.g. SegmentedBar, avatar stack) */}
      {footer && (
        <div className={cn(showOrb && "relative")}>
          {footer}
        </div>
      )}
    </Card>
  );

  if (!description) return content;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent side="top" className="max-w-xs">
        <p>{description}</p>
      </TooltipContent>
    </Tooltip>
  );
}
