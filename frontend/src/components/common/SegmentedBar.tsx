import { motion, useInView } from "framer-motion";
import { useRef } from "react";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface SegmentedBarSegment {
  label: string;
  value: number;
  colorClass: string;
}

export interface SegmentedBarProps {
  segments: SegmentedBarSegment[];
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

export function SegmentedBar({ segments, className }: SegmentedBarProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(containerRef, { once: true, margin: "-30px" });

  const total = segments.reduce((sum, s) => sum + s.value, 0);
  if (total === 0) return null;

  return (
    <div ref={containerRef} className={cn("mt-4 space-y-1.5", className)}>
      <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-border">
        {segments.map((seg, i) => {
          const pct = (seg.value / total) * 100;
          return (
            <SegmentBarItem
              key={`${seg.label}-${i}`}
              colorClass={seg.colorClass}
              width={pct}
              delay={i * 0.1}
              isLast={i === segments.length - 1}
              isInView={isInView}
            />
          );
        })}
      </div>

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

function SegmentBarItem({
  colorClass,
  width,
  delay,
  isLast,
  isInView,
}: {
  colorClass: string;
  width: number;
  delay: number;
  isLast: boolean;
  isInView: boolean;
}) {
  return (
    <motion.div
      className={cn("h-full", colorClass, isLast && "rounded-r-full")}
      initial={{ scaleX: 0 }}
      animate={{ scaleX: isInView ? 1 : 0 }}
      transition={{
        duration: 0.6,
        delay: isInView ? delay : 0,
        ease: [0.16, 1, 0.3, 1],
      }}
      style={{ transformOrigin: "left", width: `${width}%` }}
    />
  );
}
