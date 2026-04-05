/**
 * PhaseBar - 四阶段彩色进度条组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 显示引入期/发展期/高潮期/收束期四个阶段的分段进度条
 */

import { motion, useInView } from "framer-motion";
import { useRef } from "react";
import { cn } from "@/lib/cn";
import type { TimelinePhase } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const PHASE_COLORS: Record<string, string> = {
  引入期: "bg-chart-1",
  发展期: "bg-chart-2",
  高潮期: "bg-chart-3",
  收束期: "bg-chart-4",
};

const PHASE_BORDER_COLORS: Record<string, string> = {
  引入期: "border-chart-1",
  发展期: "border-chart-2",
  高潮期: "border-chart-3",
  收束期: "border-chart-4",
};

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface PhaseBarProps {
  phases: TimelinePhase[];
  activePhase?: string;
  onPhaseClick?: (phase: TimelinePhase) => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function PhaseBar({
  phases,
  activePhase,
  onPhaseClick,
  className,
}: PhaseBarProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(containerRef, { once: true, margin: "-30px" });

  if (!phases || phases.length === 0) {
    return null;
  }

  return (
    <div ref={containerRef} className={cn("space-y-2", className)}>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full border border-border">
        {phases.map((phase, i) => {
          const isActive = activePhase === phase.name;
          return (
            <PhaseSegment
              key={phase.name}
              phase={phase}
              colorClass={PHASE_COLORS[phase.name] || "bg-primary"}
              borderColorClass={PHASE_BORDER_COLORS[phase.name] || "border-primary"}
              isActive={isActive}
              delay={i * 0.1}
              isInView={isInView}
              onClick={() => onPhaseClick?.(phase)}
            />
          );
        })}
      </div>

      <div className="flex w-full items-start justify-between px-1">
        {phases.map((phase) => {
          const isActive = activePhase === phase.name;
          return (
            <button
              key={phase.name}
              onClick={() => onPhaseClick?.(phase)}
              className={cn(
                "flex items-center gap-1.5 transition-colors",
                "hover:opacity-80 cursor-pointer",
                isActive && "font-medium"
              )}
            >
              <div
                className={cn(
                  "h-2.5 w-2.5 shrink-0 rounded-sm",
                  PHASE_COLORS[phase.name] || "bg-primary",
                  isActive && "ring-2 ring-offset-1",
                  PHASE_BORDER_COLORS[phase.name] || "ring-primary"
                )}
              />
              <span
                className={cn(
                  "text-xs text-text-muted",
                  isActive && "text-text font-medium"
                )}
              >
                {phase.name} {Math.round(phase.ratio * 100)}%
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                    */
/* ------------------------------------------------------------------ */

interface PhaseSegmentProps {
  phase: TimelinePhase;
  colorClass: string;
  borderColorClass: string;
  isActive: boolean;
  delay: number;
  isInView: boolean;
  onClick?: () => void;
}

function PhaseSegment({
  phase,
  colorClass,
  borderColorClass,
  isActive,
  delay,
  isInView,
  onClick,
}: PhaseSegmentProps) {
  const widthPercent = phase.ratio * 100;

  return (
    <motion.button
      className={cn(
        "h-full transition-all cursor-pointer",
        colorClass,
        isActive && ["ring-2 ring-offset-1", borderColorClass]
      )}
      style={{ width: `${widthPercent}%` }}
      initial={{ scaleX: 0 }}
      animate={{ scaleX: isInView ? 1 : 0 }}
      transition={{
        duration: 0.5,
        delay: isInView ? delay : 0,
        ease: [0.16, 1, 0.3, 1],
      }}
      onClick={onClick}
      whileHover={{ opacity: 0.85 }}
      title={`${phase.name}: 第${phase.start}-${phase.end}块 (${Math.round(phase.ratio * 100)}%)`}
    />
  );
}
