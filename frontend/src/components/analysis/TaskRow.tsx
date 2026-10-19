/** 单行任务身份、状态与操作按钮 */
import { Circle, CheckCircle, XCircle, Loader2, Square, Eye, Trash2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { taskStatusConfig } from "@/lib/utils";
import type { TaskStatus } from "@/api/types";

export interface TaskRowProps {
  task: {
    task_id: string;
    status: TaskStatus;
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
  const canCancel = canCancelStatus(task.status);
  const canResume = canResumeStatus(task.status);

  const displayLabel = config.label;

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
