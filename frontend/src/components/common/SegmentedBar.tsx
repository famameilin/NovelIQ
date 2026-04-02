import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface SegmentedBarSegment {
  label: string;
  value: number;
  /** Tailwind background class, e.g. "bg-primary" */
  colorClass: string;
}

export interface SegmentedBarProps {
  segments: SegmentedBarSegment[];
  /** Additional className for the entire wrapper */
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function SegmentedBar({ segments, className }: SegmentedBarProps) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  if (total === 0) return null;

  return (
    <div className={cn("mt-4 space-y-1.5", className)}>
      {/* Bar — same h-1.5 as MetricCard progress bar */}
      <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-border">
        {segments.map((seg) => {
          const pct = (seg.value / total) * 100;
          return (
            <div
              key={seg.label}
              className={cn(
                "h-full transition-all duration-500",
                "first:rounded-l-full last:rounded-r-full",
                seg.colorClass,
              )}
              style={{ width: `${pct}%` }}
            />
          );
        })}
      </div>

      {/* Legend row — markers evenly distributed left / center / right */}
      <div className="flex w-full items-start justify-between">
        {segments.map((seg) => (
          <div key={seg.label} className="flex items-center gap-1">
            <div
              className={cn(
                "h-[5px] w-[5px] shrink-0 rotate-45 rounded-[1px]",
                seg.colorClass,
              )}
            />
            <span className="text-[10px] leading-none text-text-muted">
              {seg.label} {seg.value}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
