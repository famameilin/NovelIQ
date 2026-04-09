/**
 * 创建时间: 2026-04-07
 * 创建者: GLM-5
 * 任务: 细粒度进度展示组件
 * 说明: 展示任务执行的详细进度，包括当前阶段、进度条、阶段列表和子任务进度
 */
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Loader2, Circle } from "lucide-react";
import { cn } from "@/lib/cn";
import { useStreamStore } from "@/store/streamStore";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface StageConfig {
  label: string;
  range: [number, number];
}

type StageKey = "preprocess" | "annotate" | "aggregate" | "topic-model" | "diagnose";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const STAGE_CONFIG: Record<StageKey, StageConfig> = {
  preprocess: { label: "预处理", range: [0, 10] },
  annotate: { label: "标注分析", range: [10, 80] },
  aggregate: { label: "数据聚合", range: [80, 90] },
  "topic-model": { label: "主题建模", range: [90, 95] },
  diagnose: { label: "诊断报告", range: [95, 100] },
};

const PHASE_CONFIG: Record<string, { label: string }> = {
  phase1: { label: "伏笔分析" },
  phase2: { label: "人物识别" },
  phase3: { label: "对话归因" },
  phase4: { label: "关系识别" },
};

const STAGE_ORDER: StageKey[] = ["preprocess", "annotate", "aggregate", "topic-model", "diagnose"];

/* ------------------------------------------------------------------ */
/*  Utils                                                             */
/* ------------------------------------------------------------------ */

function getStageStatus(
  stageKey: StageKey,
  currentPercent: number
): "completed" | "current" | "pending" {
  const config = STAGE_CONFIG[stageKey];
  const [start, end] = config.range;

  if (currentPercent >= end) {
    return "completed";
  }
  if (currentPercent >= start) {
    return "current";
  }
  return "pending";
}

function getCurrentStageKey(percent: number): StageKey | null {
  for (const key of STAGE_ORDER) {
    const config = STAGE_CONFIG[key];
    if (percent >= config.range[0] && percent < config.range[1]) {
      return key;
    }
  }
  if (percent >= 100) {
    return "diagnose";
  }
  return null;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export interface ProgressDetailProps {
  className?: string;
}

export function ProgressDetail({ className }: ProgressDetailProps) {
  const progress = useStreamStore((state) => state.progress);
  const stageDurations = useStreamStore((state) => state.stageDurations);

  if (!progress) {
    return null;
  }

  const { stage, sub_stage, current, total, percent, message } = progress;
  const currentStageKey = getCurrentStageKey(percent);

  return (
    <div className={cn("space-y-4", className)}>
      <ProgressBar
        stage={stage}
        phase={sub_stage}
        current={current}
        total={total}
        percent={percent}
        message={message}
      />

      <StageList
        currentPercent={percent}
        stageDurations={stageDurations}
        currentStageKey={currentStageKey}
      />

      {sub_stage && (
        <SubTaskProgress subStage={sub_stage} current={current} total={total} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub Components                                                    */
/* ------------------------------------------------------------------ */

interface ProgressBarProps {
  stage: string;
  phase?: string;
  current: number;
  total: number;
  percent: number;
  message?: string;
}

function ProgressBar({ stage, phase, current, total, percent, message }: ProgressBarProps) {
  const stageLabel = STAGE_CONFIG[stage as StageKey]?.label ?? stage;
  const phaseLabel = phase ? PHASE_CONFIG[phase]?.label : null;
  const displayLabel = phaseLabel ? `${stageLabel} - ${phaseLabel}` : stageLabel;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-text-primary">{displayLabel}</span>
        <div className="flex items-center gap-4">
          <span className="text-xs text-text-muted">
            chunk {current}/{total}
          </span>
          <span className="text-xs font-medium tabular-nums text-primary">
            {percent.toFixed(1)}%
          </span>
        </div>
      </div>

      <div className="relative h-2 w-full overflow-hidden rounded-full bg-surface-hover">
        <div
          className="h-full bg-primary"
          style={{ width: `${percent}%` }}
        />
      </div>

      <AnimatePresence mode="wait">
        {message && (
          <motion.p
            key={message}
            initial={{ opacity: 0, y: -5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            transition={{ duration: 0.2 }}
            className="text-xs text-text-muted"
          >
            {message}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}

interface StageListProps {
  currentPercent: number;
  stageDurations: Map<string, number>;
  currentStageKey: StageKey | null;
}

function StageList({ currentPercent, stageDurations, currentStageKey }: StageListProps) {
  return (
    <div className="space-y-1.5">
      {STAGE_ORDER.map((stageKey) => {
        const config = STAGE_CONFIG[stageKey];
        const status = getStageStatus(stageKey, currentPercent);
        const duration = stageDurations.get(stageKey);

        return (
          <StageItem
            key={stageKey}
            label={config.label}
            status={status}
            duration={duration}
            isActive={currentStageKey === stageKey}
          />
        );
      })}
    </div>
  );
}

interface StageItemProps {
  label: string;
  status: "completed" | "current" | "pending";
  duration?: number;
  isActive: boolean;
}

function StageItem({ label, status, duration, isActive }: StageItemProps) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3 }}
      className={cn(
        "flex items-center justify-between rounded-md px-2 py-1.5",
        isActive && "bg-surface-hover"
      )}
    >
      <div className="flex items-center gap-2">
        <StageIcon status={status} />
        <span
          className={cn(
            "text-sm",
            status === "completed" && "text-text-primary",
            status === "current" && "font-medium text-primary",
            status === "pending" && "text-text-muted"
          )}
        >
          {label}
        </span>
      </div>

      {duration !== undefined && status === "completed" && (
        <span className="text-xs text-text-muted">{formatDuration(duration)}</span>
      )}
    </motion.div>
  );
}

interface StageIconProps {
  status: "completed" | "current" | "pending";
}

function StageIcon({ status }: StageIconProps) {
  if (status === "completed") {
    return <CheckCircle2 className="h-4 w-4 text-success" />;
  }

  if (status === "current") {
    return (
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
      >
        <Loader2 className="h-4 w-4 text-primary" />
      </motion.div>
    );
  }

  return <Circle className="h-4 w-4 text-text-muted" />;
}

interface SubTaskProgressProps {
  subStage: string;
  current: number;
  total: number;
}

function SubTaskProgress({ subStage, current, total }: SubTaskProgressProps) {
  if (total === 0) return null;

  const subPercent = (current / total) * 100;
  const phaseLabel = PHASE_CONFIG[subStage]?.label ?? subStage;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-md bg-surface-hover p-3"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-text-secondary">{phaseLabel}</span>
      </div>

      <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-border">
        <motion.div
          className="h-full bg-primary/60"
          initial={{ width: 0 }}
          animate={{ width: `${subPercent}%` }}
          transition={{ duration: 0.2, ease: "easeOut" }}
        />
      </div>
    </motion.div>
  );
}
