import type { ReactNode } from "react";
import { useRef, useState, useEffect } from "react";
import { motion, useInView } from "framer-motion";
import { Card } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  METRIC_ACCENT_BAR_CLASS_MAP,
  METRIC_ACCENT_CARD_CLASS_MAP,
  getMetricAccentColor,
  type MetricAccent,
} from "@/components/common/DashboardCardShell";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export type MetricFormat = "number" | "percent" | "score" | "raw";

export type { MetricAccent } from "@/components/common/DashboardCardShell";

export interface MetricCardProps {
  label: string;
  value: number;
  format?: MetricFormat;
  maxScore?: number;
  decimals?: number;
  icon?: ReactNode;
  description?: string;
  className?: string;
  accent?: MetricAccent;
  trend?: string;
  footer?: ReactNode;
  showOrb?: boolean;
  showBar?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Accent → static Tailwind classes                                   */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：保留原有数值进度逻辑，同时复用共享卡片壳使用的比例计算方式
 */
function barWidth(format: MetricFormat, value: number, maxScore: number): number {
  if (format === "score") return Math.min(value / maxScore, 1) * 100;
  if (format === "percent") return Math.min(value, 1) * 100;
  return 0;
}

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：统一 MetricCard 和业务卡片的数字格式化逻辑，避免视觉重构时数值展示回归
 */
function formatValue(raw: number, format: MetricFormat, decimals: number, maxScore: number): string {
  switch (format) {
    case "percent":
      return `${(raw * 100).toFixed(decimals)}%`;
    case "score":
      return `${raw.toFixed(decimals)}/${maxScore}`;
    case "number":
      return raw.toFixed(decimals);
    case "raw":
    default:
      return Number.isInteger(raw) ? String(raw) : raw.toFixed(decimals);
  }
}

/* ------------------------------------------------------------------ */
/*  Animated Number (RAF-based, no IntersectionObserver)              */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：保留 MetricCard 数字滚动能力，作为共享视觉原语的一部分继续复用
 */
function AnimatedNumber({
  raw,
  format,
  decimals,
  maxScore,
}: {
  raw: number;
  format: MetricFormat;
  decimals: number;
  maxScore: number;
}) {
  const [display, setDisplay] = useState("0");
  const rafRef = useRef<number | null>(null);
  const prevRef = useRef<number>(0);

  useEffect(() => {
    const start = prevRef.current;
    const duration = 600;
    let startTime: number | null = null;

    const tick = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = start + (raw - start) * eased;

      setDisplay(formatValue(current, format, decimals, maxScore));

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        if (startTime !== null) {
          const elapsed = performance.now() - startTime;
          const progress = Math.min(elapsed / duration, 1);
          const eased = 1 - Math.pow(1 - progress, 3);
          prevRef.current = start + (raw - start) * eased;
        }
      }
    };
  }, [raw, format, decimals, maxScore]);

  return (
    <span className="mt-0.5 text-2xl font-bold tabular-nums text-text">
      {display}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Animated Bar (Framer Motion)                                       */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：继续复用 MetricCard 的进度条动画，同时接入共享 accent 色板
 */
function AnimatedBar({
  fillPct,
  barGradient,
}: {
  fillPct: number;
  barGradient: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-30px" });

  return (
    <motion.div
      ref={ref}
      className={cn("h-full rounded-full", barGradient)}
      initial={{ scaleX: 0 }}
      animate={{ scaleX: isInView ? 1 : 0 }}
      transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
      style={{ transformOrigin: "left", width: `${fillPct}%` }}
    />
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：改为复用共享 accent 原语，确保 MetricCard 与仪表盘业务卡片保持同一套视觉基线
 */
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
  const autoBar = format === "score" || format === "percent";
  const showBar = autoBar || forceBar;
  const fillPct = autoBar ? barWidth(format, value, maxScore) : Math.min(value, 100);
  const accentCard = METRIC_ACCENT_CARD_CLASS_MAP[accent];
  const barGradient = METRIC_ACCENT_BAR_CLASS_MAP[accent];

  const content = (
    <Card
      variant="elevated"
      className={cn(accentCard, "relative rounded-xl p-5", className)}
    >
      {showOrb && (
        <div
          className={cn(
            "pointer-events-none absolute h-24 w-24 rounded-full blur-2xl",
            accent === "primary" ? "-right-4 -top-4" : "-bottom-6 -right-6 h-20 w-20",
          )}
          style={{ backgroundColor: getMetricAccentColor(accent, 0.05) }}
        />
      )}

      <div className={cn(showOrb && "relative flex items-start justify-between")}>
        <div className="flex items-center gap-3">
          {icon && (
            <div
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
              style={{
                backgroundColor: getMetricAccentColor(accent, 0.1),
                color: getMetricAccentColor(accent),
              }}
            >
              {icon}
            </div>
          )}
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
              {label}
            </p>
            <AnimatedNumber
              raw={value}
              format={format}
              decimals={decimals}
              maxScore={maxScore}
            />
          </div>
        </div>

        {trend && (
          <div
            className="flex h-8 items-center gap-1 rounded-full px-3 text-xs font-medium"
            style={{
              backgroundColor: getMetricAccentColor(accent, 0.1),
              color: getMetricAccentColor(accent),
            }}
          >
            {trend}
          </div>
        )}
      </div>

      {showBar && (
        <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-border">
          <AnimatedBar fillPct={fillPct} barGradient={barGradient} />
        </div>
      )}

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
