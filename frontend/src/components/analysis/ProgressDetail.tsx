/** 展示任务执行的详细进度，包括当前阶段、进度条和子任务进度 */
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, Loader2, Circle } from "lucide-react";
import { cn } from "@/lib/cn";
import { useStreamStore } from "@/store/streamStore";

interface StageConfig {
  label: string;
  range: [number, number];
}

type StageKey = "preprocess" | "annotate" | "aggregate" | "topic-model" | "diagnose";

const STAGE_CONFIG: Record<StageKey, StageConfig> = {
  preprocess: { label: "预处理", range: [0, 10] },
  annotate: { label: "标注分析", range: [10, 80] },
  aggregate: { label: "数据聚合", range: [80, 90] },
  "topic-model": { label: "主题建模", range: [90, 95] },
  diagnose: { label: "诊断报告", range: [95, 100] },
};

// 修改时间: 2026-08-02
// 任务: agent 化改造
// 原因: 阶段 1-4 已合并为标注 Agent 任务，消歧集成进 agent 循环；
//       前端子阶段只展示 agent / sub_agent 两种粒度。
const PHASE_CONFIG: Record<string, { label: string }> = {
  agent: { label: "标注 Agent" },
  sub_agent: { label: "子代理" },
};

const STAGE_ORDER: StageKey[] = ["preprocess", "annotate", "aggregate", "topic-model", "diagnose"];

function getStageStatus(
  stageKey: StageKey,
  currentPercent: number,
  currentStageKey: StageKey | null
): "completed" | "current" | "pending" {
  if (currentStageKey) {
    const currentStageIndex = STAGE_ORDER.indexOf(currentStageKey);
    const stageIndex = STAGE_ORDER.indexOf(stageKey);
    if (stageIndex < currentStageIndex) {
      return "completed";
    }
    if (stageIndex === currentStageIndex) {
      return "current";
    }
    return "pending";
  }

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

function resolveCurrentStageKey(stage: string, percent: number): StageKey | null {
  if (stage in STAGE_CONFIG) {
    return stage as StageKey;
  }
  return getCurrentStageKey(percent);
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
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

  const { stage, sub_stage, current, total, percent, sub_percent, message } = progress;
  const currentStageKey = resolveCurrentStageKey(stage, percent);

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
        <SubTaskProgress subStage={sub_stage} subPercent={sub_percent} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  子组件                                                             */
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
        const status = getStageStatus(stageKey, currentPercent, currentStageKey);
        const duration = stageDurations.get(stageKey);

        return (
          <StageItem
            key={stageKey}
            stageKey={stageKey}
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
  stageKey: StageKey;
  label: string;
  status: "completed" | "current" | "pending";
  duration?: number;
  isActive: boolean;
}

function StageItem({ stageKey, label, status, duration, isActive }: StageItemProps) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3 }}
      data-testid={`stage-item-${stageKey}`}
      data-status={status}
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
  subPercent: number;
}

function SubTaskProgress({ subStage, subPercent }: SubTaskProgressProps) {
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
        {subPercent < 100 && (
          <Loader2 className="h-3 w-3 text-primary animate-spin" />
        )}
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
