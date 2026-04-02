import { useRef, useId } from "react";
import { motion, useInView } from "framer-motion";
import { cn } from "@/lib/cn";

export interface AnalysisProgressRingProps {
  progress: number;
  size?: number;
  strokeWidth?: number;
  label?: string;
  className?: string;
}

export function AnalysisProgressRing({
  progress,
  size = 48,
  strokeWidth = 4,
  label,
  className,
}: AnalysisProgressRingProps) {
  const ref = useRef<HTMLDivElement>(null);
  useInView(ref, { once: true, margin: "-20px" });

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedProgress = Math.max(0, Math.min(100, progress));

  const gradientId = `progress-ring-${useId()}`;

  return (
    <div
      ref={ref}
      className={cn("relative inline-flex items-center justify-center", className)}
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={Math.round(clampedProgress)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? `进度 ${Math.round(clampedProgress)}%`}
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
            <stop offset="0%" className="stop-color-primary" />
            <stop offset="100%" className="stop-color-primary-hover" />
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
          animate={{ strokeDashoffset: circumference - (clampedProgress / 100) * circumference }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          style={{ strokeDasharray: circumference }}
        />
      </svg>
      <span className="absolute text-[10px] font-semibold tabular-nums text-text-secondary">
        {label ?? `${Math.round(clampedProgress)}%`}
      </span>
    </div>
  );
}
