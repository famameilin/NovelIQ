/**
 * TaskRow - 单行任务条目组件
 *
 * 显示单个任务的状态、时间和操作按钮
 *
 * - 移除伪状态 (chunking/annotating/...)，统一使用后端 TaskStatus
 * - 运行中任务从 streamStore 读取 progress.stage 显示具体阶段
 *
 * 为 pending 任务补齐继续入口，并把“实时流式中”语义收窄到 running/cancelling，避免把可恢复任务误显示成运行中
 */
import { Circle, CheckCircle, XCircle, Loader2, Square, Eye, Trash2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { taskStatusConfig } from "@/lib/utils";
import { useStreamStore } from "@/store/streamStore";
import type { TaskStatus } from "@/api/types";

/** 后端 stage → 前端显示文案 */
const STAGE_LABELS: Record<string, string> = {
  preprocess: "预处理",
  annotate: "标注分析",
  aggregate: "数据聚合",
  "topic-model": "主题建模",
  diagnose: "诊断报告",
};

export interface TaskRowProps {
  task: {
    task_id: string;
    status: TaskStatus;
    created_at: string | null;
  };
  isActive: boolean;
  onSelect: (taskId: string) => void;
  onCancel: (taskId: string) => void;
  onDelete: (taskId: string) => void;
  onResume?: (taskId: string) => void;
}

function getStatusIcon(status: TaskStatus) {
  switch (status) {
    case "pending":
      return <Circle className="h-4 w-4 text-text-muted" />;
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
    case "cancelling":
      return <Loader2 className="h-4 w-4 animate-spin text-warning" />;
    case "cancelled":
      return <XCircle className="h-4 w-4 text-text-muted" />;
    case "completed":
      return <CheckCircle className="h-4 w-4 text-success" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-destructive" />;
    default:
      return <Circle className="h-4 w-4 text-text-muted" />;
  }
}

function formatRelativeTime(dateStr: string | null): string {

  // 与 TaskRowProps.created_at 的可空语义保持一致，避免严格类型检查构建失败
  // 列表接口历史上可能漏传 created_at，前端需要兜底避免显示 epoch 假时间
  if (!dateStr) return "未知时间";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return "未知时间";
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "刚刚";
  if (diffMins < 60) return `${diffMins}分钟前`;
  if (diffHours < 24) return `${diffHours}小时前`;
  if (diffDays < 7) return `${diffDays}天前`;
  return date.toLocaleDateString();
}

function isStreamingStatus(status: TaskStatus): boolean {
  return ["running", "cancelling"].includes(status);
}

function canCancelStatus(status: TaskStatus): boolean {
  return ["pending", "running"].includes(status);
}

function canResumeStatus(status: TaskStatus): boolean {
  return ["pending", "failed", "cancelled"].includes(status);
}

export function TaskRow({
  task,
  isActive,
  onSelect,
  onCancel,
  onDelete,
  onResume,
}: TaskRowProps) {
  const config = taskStatusConfig[task.status] ?? taskStatusConfig.pending;
  const isStreaming = isStreamingStatus(task.status);
  const canCancel = canCancelStatus(task.status);
  const canResume = canResumeStatus(task.status);

  // 从 streamStore 读取当前 SSE 推送的 stage，仅对活跃的运行中任务生效
  const progress = useStreamStore((s) => s.progress);
  const currentTaskId = useStreamStore((s) => s.currentTaskId);

  // 活跃的运行中任务显示具体阶段，否则用默认 label
  const isActiveRunning = isActive && isStreaming && currentTaskId === task.task_id && progress?.stage;
  const displayLabel = isActiveRunning && progress?.stage
    ? `${STAGE_LABELS[progress.stage] ?? progress.stage}中`
    : config.label;

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors",
        "hover:bg-surface-hover cursor-pointer",
        isActive && "bg-primary-subtle"
      )}
      onClick={() => onSelect(task.task_id)}
    >
      <div className="flex-shrink-0">{getStatusIcon(task.status)}</div>

      <div className="min-w-0 flex-1 overflow-hidden">
        <div className="flex items-center gap-1.5">
          <span className="truncate font-mono text-xs text-text">
            {task.task_id.slice(0, 8)}
          </span>
          <Badge variant={config.variant} className="text-[10px] px-1 py-0">
            {displayLabel}
          </Badge>
        </div>
        <div className="text-[10px] text-text-muted">
          {formatRelativeTime(task.created_at)}
        </div>
      </div>

      <div className="flex flex-shrink-0 items-center">
        {task.status === "completed" && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(task.task_id);
            }}
          >
            <Eye className="h-3 w-3" />
          </Button>
        )}

        {canCancel && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-warning hover:text-warning"
            onClick={(e) => {
              e.stopPropagation();
              onCancel(task.task_id);
            }}
          >
            <Square className="h-3 w-3" />
          </Button>
        )}

        {!canCancel && task.status !== "failed" && task.status !== "pending" && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-text-muted hover:text-destructive"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(task.task_id);
            }}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        )}

        {canResume && (
          <>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-primary hover:text-primary"
              onClick={(e) => {
                e.stopPropagation();
                onResume?.(task.task_id);
              }}
              title="继续分析"
            >
              <RotateCcw className="h-3 w-3" />
            </Button>
            {task.status === "failed" && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-text-muted hover:text-destructive"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(task.task_id);
                }}
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
