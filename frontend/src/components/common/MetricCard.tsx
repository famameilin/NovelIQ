import type { ReactNode } from "react";
import { useRef, useState, useEffect } from "react";
import { motion, useInView } from "framer-motion";
import { Card } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export type MetricFormat = "number" | "percent" | "score" | "raw";

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
  accent?: MetricAccent;
  trend?: string;
  footer?: ReactNode;
  showOrb?: boolean;
  showBar?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Accent → static Tailwind classes                                   */
/* ------------------------------------------------------------------ */

const ACCENT_MAP: Record<
  MetricAccent,
  { card: string; bar: string }
> = {
  primary: {
    card: "bg-gradient-to-br from-surface via-surface to-primary/15 hover:border-primary/30",
    bar: "bg-primary",
  },
  "chart-1": {
    card: "bg-gradient-to-br from-surface via-surface to-chart-1/15 hover:border-chart-1/30",
    bar: "bg-chart-1",
  },
  "chart-2": {
    card: "bg-gradient-to-br from-surface via-surface to-chart-2/15 hover:border-chart-2/30",
    bar: "bg-chart-2",
  },
  "chart-3": {
    card: "bg-gradient-to-br from-surface via-surface to-chart-3/15 hover:border-chart-3/30",
    bar: "bg-chart-3",
  },
  "chart-4": {
    card: "bg-gradient-to-br from-surface via-surface to-chart-4/15 hover:border-chart-4/30",
    bar: "bg-chart-4",
  },
  "chart-5": {
    card: "bg-gradient-to-br from-surface via-surface to-chart-5/15 hover:border-chart-5/30",
    bar: "bg-chart-5",
  },
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function barWidth(format: MetricFormat, value: number, maxScore: number): number {
  if (format === "score") return Math.min(value / maxScore, 1) * 100;
  if (format === "percent") return Math.min(value, 1) * 100;
  return 0;
}

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
      } else {
        prevRef.current = raw;
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
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
  const { card: accentCard, bar: barGradient } = ACCENT_MAP[accent];

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
          style={{ backgroundColor: `hsl(var(--${accent}) / 0.05)` }}
        />
      )}

      <div className={cn(showOrb && "relative flex items-start justify-between")}>
        <div className="flex items-center gap-3">
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
              backgroundColor: `hsl(var(--${accent}) / 0.1)`,
              color: `hsl(var(--${accent}))`,
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
