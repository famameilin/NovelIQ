import { cn } from "@/lib/cn";

export interface AnalysisProgressRingProps {
  /** Progress value 0-100 */
  progress: number;
  /** Ring diameter in pixels */
  size?: number;
  /** Stroke width in pixels */
  strokeWidth?: number;
  /** Optional label shown in center */
  label?: string;
  /** Additional className on the wrapper */
  className?: string;
}

export function AnalysisProgressRing({
  progress,
  size = 48,
  strokeWidth = 4,
  label,
  className,
}: AnalysisProgressRingProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedProgress = Math.max(0, Math.min(100, progress));
  const offset = circumference - (clampedProgress / 100) * circumference;

  const gradientId = `progress-ring-${Math.random().toString(36).slice(2, 9)}`;

  return (
    <div
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
        {/* Gradient definition — CSS class sets stop-color via CSS variables */}
        <defs>
          <linearGradient id={gradientId} gradientUnits="userSpaceOnUse">
            <stop offset="0%" className="stop-color-primary" />
            <stop offset="100%" className="stop-color-primary-hover" />
          </linearGradient>
        </defs>
        {/* Background track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="stroke-border"
        />
        {/* Progress arc — gradient */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          stroke={`url(#${gradientId})`}
          className="transition-[stroke-dashoffset] duration-500 ease-out"
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: offset,
          }}
        />
      </svg>
      <span className="absolute text-[10px] font-semibold tabular-nums text-text-secondary">
        {label ?? `${Math.round(clampedProgress)}%`}
      </span>
    </div>
  );
}
