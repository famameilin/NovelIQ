import { useQuery } from "@tanstack/react-query";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { getAnalysisTasks } from "@/api/analysis";
import { useNovelStore } from "@/store/novelStore";
import { taskStatusConfig } from "@/lib/utils";

export interface TaskSelectorProps {
  novelId: string;
  novelTitle?: string;
  className?: string;
}

export function TaskSelector({ novelId, novelTitle, className }: TaskSelectorProps) {
  const { currentTaskId, setTask } = useNovelStore();

  const { data: tasks, isLoading } = useQuery({
    queryKey: ["novels", novelId, "tasks"],
    queryFn: () => getAnalysisTasks(novelId),
    enabled: !!novelId,
    staleTime: 30_000,
  });

  const taskList = tasks ?? [];

  if (isLoading) {
    return (
      <div className="h-9 w-48 animate-pulse rounded-md bg-surface-hover" />
    );
  }

  if (taskList.length === 0) {
    return (
      <span className="text-sm text-text-muted">暂无分析任务</span>
    );
  }

  return (
    <Select value={currentTaskId ?? ""} onValueChange={setTask}>
      <SelectTrigger className={className ?? "w-56"}>
        <SelectValue placeholder={novelTitle ? `小说 ${novelTitle}` : "选择分析任务"} />
      </SelectTrigger>
      <SelectContent>
        {taskList.map((task) => {
          const config = taskStatusConfig[task.status] ?? taskStatusConfig.pending;
          return (
            <SelectItem key={task.task_id} value={task.task_id}>
              <span className="flex items-center gap-2">
                <span className="truncate font-mono text-xs">
                  {task.task_id.slice(0, 8)}
                </span>
                <Badge variant={config.variant} className="text-[10px] px-1.5 py-0">
                  {config.label}
                </Badge>
              </span>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}
