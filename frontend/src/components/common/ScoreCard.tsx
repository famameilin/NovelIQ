import { useRef } from "react";
import { useInView } from "framer-motion";
import { useId } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";

export interface ScoreCardProps {
  title: string;
  /** 数值类型: 'percent' | 'score' */
  type?: "percent" | "score";
  /** 百分比值 (0-100) */
  value?: number | null;
  /** 评分值 (0-5) */
  score?: number | null;
  /** 说明文字 */
  reason?: string | null;
  /** 最大分数 (默认5) */
  maxScore?: number;
  className?: string;
}

/**
 * 评分卡片 - 支持环形进度图和圆点评分条两种模式
 */
export function ScoreCard({
  title,
  type = "percent",
  value,
  score,
  reason,
  maxScore = 5,
  className,
}: ScoreCardProps) {
  const isPercent = type === "percent";
  const displayValue = isPercent ? value : score;
  const isValid = displayValue != null && !isNaN(displayValue as number);

  return (
    <Card
      variant="elevated"
      className={cn("rounded-xl overflow-hidden", className)}
    >
      <CardContent className="flex flex-col gap-3 p-5">
        <h4 className="text-sm font-semibold text-text">{title}</h4>

        <div className="flex items-center gap-4">
          {isPercent ? (
            <ProgressRing value={value} size={56} />
          ) : (
            <ScoreBar score={score} maxScore={maxScore} />
          )}

          <div className="flex-1 min-w-0">
            {isValid ? (
              <p className="text-2xl font-bold text-text tabular-nums">
                {isPercent ? `${Math.round(displayValue as number)}%` : `${displayValue}/${maxScore}`}
              </p>
            ) : (
              <p className="text-lg text-text-muted">暂无数据</p>
            )}
          </div>
        </div>

        {reason && (
          <p className="text-xs text-text-muted line-clamp-2">{reason}</p>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * 环形进度图 - 用于百分比展示
 */
function ProgressRing({
  value,
  size = 56,
  strokeWidth = 5,
}: {
  value?: number | null;
  size?: number;
  strokeWidth?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-20px" });
  const gradientId = useId();

  if (value == null || isNaN(value)) {
    return (
      <div
        ref={ref}
        className="flex items-center justify-center rounded-full bg-surface-hover"
        style={{ width: size, height: size }}
      >
        <span className="text-xs text-text-muted">—</span>
      </div>
    );
  }

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedValue = Math.max(0, Math.min(100, value));

  return (
    <div
      ref={ref}
      className="relative inline-flex items-center justify-center shrink-0"
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={Math.round(clampedValue)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`${Math.round(clampedValue)}%`}
    >
      <svg
        width={size}
        height={size}
        className="-rotate-90"
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={gradientId} gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="hsl(var(--primary))" />
            <stop offset="100%" stopColor="hsl(var(--primary-hover))" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="stroke-border"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          stroke={`url(#${gradientId})`}
          initial={{ strokeDashoffset: circumference }}
          animate={
            isInView
              ? { strokeDashoffset: circumference - (clampedValue / 100) * circumference }
              : { strokeDashoffset: circumference }
          }
          transition={{ duration: 0.8, ease: "easeOut" }}
          style={{ strokeDasharray: circumference }}
        />
      </svg>
    </div>
  );
}

/**
 * 圆点评分条 - 用于 0-5 分展示
 */
function ScoreBar({
  score,
  maxScore = 5,
}: {
  score?: number | null;
  maxScore?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-20px" });

  if (score == null || isNaN(score)) {
    return (
      <div ref={ref} className="flex items-center gap-1">
        {Array.from({ length: maxScore }).map((_, i) => (
          <div
            key={i}
            className="h-3 w-3 rounded-full border border-border"
          />
        ))}
      </div>
    );
  }

  const clampedScore = Math.max(0, Math.min(maxScore, score));

  return (
    <div ref={ref} className="flex items-center gap-1" role="img" aria-label={`评分 ${clampedScore}/${maxScore}`}>
      {Array.from({ length: maxScore }).map((_, i) => (
        <motion.svg
          key={i}
          width={12}
          height={12}
          viewBox="0 0 12 12"
          initial={{ opacity: 0, scale: 0.5 }}
          animate={isInView ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.5 }}
          transition={{ duration: 0.3, delay: i * 0.05 }}
          aria-hidden="true"
        >
          <circle
            cx={6}
            cy={6}
            r={5}
            className={i < clampedScore ? "fill-primary" : "fill-border stroke-border stroke-[0.5]"}
          />
        </motion.svg>
      ))}
    </div>
  );
}