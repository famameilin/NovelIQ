/**
 * TaskRow - 单行任务条目组件
 *
 * 创建时间: 2026-04-07
 * 创建者: TraeAI
 * 任务: implement-task-cancellation
 * 说明: 显示单个任务的状态、时间和操作按钮
 */
import { Circle, CheckCircle, XCircle, Loader2, Square, Eye, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { taskStatusConfig } from "@/lib/utils";
import type { TaskStatus } from "@/api/types";

export interface TaskRowProps {
  task: {
    task_id: string;
    status: TaskStatus;
    created_at: string;
  };
  isActive: boolean;
  onSelect: (taskId: string) => void;
  onCancel: (taskId: string) => void;
  onDelete: (taskId: string) => void;
}

function getStatusIcon(status: TaskStatus) {
  switch (status) {
    case "pending":
      return <Circle className="h-4 w-4 text-text-muted" />;
    case "chunking":
    case "annotating":
    case "aggregating":
    case "diagnosing":
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

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
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

function isRunningStatus(status: TaskStatus): boolean {
  return ["pending", "chunking", "annotating", "aggregating", "diagnosing", "cancelling"].includes(status);
}

export function TaskRow({
  task,
  isActive,
  onSelect,
  onCancel,
  onDelete,
}: TaskRowProps) {
  const config = taskStatusConfig[task.status] ?? taskStatusConfig.pending;
  const isRunning = isRunningStatus(task.status);

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
            {config.label}
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

        {isRunning && task.status !== "cancelling" && (
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

        {!isRunning && (
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
      </div>
    </div>
  );
}
