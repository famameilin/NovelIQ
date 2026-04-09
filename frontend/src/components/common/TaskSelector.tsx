import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Search } from "lucide-react";
import { getAnalysisTasks } from "@/api/analysis";
import { useNovelStore } from "@/store/novelStore";
import { taskStatusConfig } from "@/lib/utils";

export interface TaskSelectorProps {
  novelId: string;
  className?: string;
}

export function TaskSelector({ novelId, className }: TaskSelectorProps) {
  const { currentTaskId, setTask } = useNovelStore();
  const [searchQuery, setSearchQuery] = useState("");

  const { data: tasks, isLoading } = useQuery({
    queryKey: ["novels", novelId, "tasks"],
    queryFn: () => getAnalysisTasks(novelId),
    enabled: !!novelId,
    staleTime: 30_000,
  });

  const filteredTasks = useMemo(() => {
    const taskList = tasks ?? [];
    if (!searchQuery.trim()) return taskList;
    const query = searchQuery.trim().toLowerCase();
    return taskList.filter(
      (task) =>
        task.task_id.toLowerCase().includes(query) ||
        (task.status && task.status.toLowerCase().includes(query))
    );
  }, [tasks, searchQuery]);

  if (isLoading) {
    return (
      <div className="h-9 w-48 animate-pulse rounded-md bg-surface-hover" />
    );
  }

  if ((tasks?.length ?? 0) === 0) {
    return (
      <span className="text-sm text-text-muted">暂无分析任务</span>
    );
  }

  return (
    <Select value={currentTaskId ?? ""} onValueChange={setTask}>
      <SelectTrigger className={className ?? "w-56"}>
        <SelectValue placeholder="选择分析任务" />
      </SelectTrigger>
      <SelectContent>
        {/* 搜索框 */}
        <div className="border-b border-border px-2 py-1.5">
          <div className="flex items-center gap-2 px-1">
            <Search className="h-3.5 w-3.5 shrink-0 text-text-muted" />
            <input
              type="text"
              placeholder="搜索任务ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-text-muted"
            />
          </div>
        </div>

        {filteredTasks.length === 0 ? (
          <div className="px-2 py-3 text-center text-xs text-text-muted">
            无匹配任务
          </div>
        ) : (
          filteredTasks.map((task) => {
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
          })
        )}
      </SelectContent>
    </Select>
  );
}
