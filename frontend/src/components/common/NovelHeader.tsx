/**
 * NovelHeader - 小说页面头部组件
 *
 * 创建时间: 2026-04-04
 * 创建者: GLM-5
 * 任务: 小说详情页头部
 * 说明: 显示小说标题、状态徽章、任务选择器和操作按钮
 *
 * 修改时间: 2026-04-07
 * 修改者: TraeAI
 * 任务: websocket-streaming-progress
 * 修改内容: 集成细粒度进度展示组件和 LLM 输出组件
 *
 * 修改时间: 2026-04-07
 * 修改者: TraeAI
 * 任务: implement-task-cancellation
 * 修改内容: 合并 TaskSelector 和 TaskPanel 为统一的任务管理下拉面板
 *
 * 修改时间: 2026-04-07
 * 修改者: TraeAI
 * 任务: code-review-fix
 * 修改内容: 移除未使用的 onCancelTask 属性，简化组件接口
 *
 * 修改时间: 2026-04-19
 * 修改者: Codex (GPT-5)
 * 任务: task-api-decouple
 * 修改内容: 拆分 onCreateTask / onResumeTask / onDeleteCurrentTask，避免混合动作语义。
 *
 * 修改时间: 2026-04-19
 * 修改者: Codex (GPT-5)
 * 任务: fix-task-system-review-findings
 * 修改内容: “运行中”计数仅统计真正执行中的 running/cancelling，避免把可恢复的 pending 任务误标成运行中。
 */
import { useState, useRef, useEffect } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Trash2, ChevronDown, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { TaskRow } from "@/components/analysis/TaskRow";
import { useNovelStore } from "@/store/novelStore";
import { cn } from "@/lib/cn";
import { taskStatusConfig } from "@/lib/utils";
import { getAnalysisTasks, cancelAnalysisTask, batchDeleteTasks } from "@/api/analysis";
import type { AnalysisTask } from "@/api/types";

export interface NovelHeaderProps {
  title: string;
  novelId?: string;
  onCreateTask?: () => void;
  onResumeTask?: (taskId: string) => void;
  onDeleteCurrentTask?: () => void;
  isResuming?: boolean;
  className?: string;
}

function getCurrentTaskDisplay(tasks: AnalysisTask[], currentTaskId: string | null) {
  if (!currentTaskId || tasks.length === 0) {
    return { id: null, status: null, config: null };
  }
  const task = tasks.find((t) => t.task_id === currentTaskId);
  if (!task) {
    return { id: currentTaskId.slice(0, 8), status: null, config: null };
  }
  const config = taskStatusConfig[task.status] ?? taskStatusConfig.pending;
  return { id: task.task_id.slice(0, 8), status: task.status, config };
}

export function NovelHeader({
  title,
  novelId: novelIdProp,
  onCreateTask,
  onResumeTask,
  onDeleteCurrentTask,
  isResuming = false,
  className,
}: NovelHeaderProps) {
  const routeParams = useParams<{ novelId: string }>();
  const novelId = novelIdProp ?? routeParams.novelId;
  const { currentTaskId, setTask } = useNovelStore();
  const queryClient = useQueryClient();
  const [taskPanelOpen, setTaskPanelOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const { data: tasks = [], isLoading: tasksLoading } = useQuery({
    queryKey: ["tasks", novelId],
    queryFn: () => getAnalysisTasks(novelId!),
    enabled: !!novelId,
  });

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        if (taskPanelOpen) setTaskPanelOpen(false);
      }
    }
    if (taskPanelOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [taskPanelOpen]);

  const runningCount = tasks.filter((t) =>
    ["running", "cancelling"].includes(t.status)
  ).length;

  const currentTaskDisplay = getCurrentTaskDisplay(tasks, currentTaskId);

  const handleSelect = (taskId: string) => {
    setTask(taskId);
    setTaskPanelOpen(false);
  };

  const handleCancel = async (taskId: string) => {
    if (!novelId) return;
    try {
      await cancelAnalysisTask(novelId, taskId);
      toast.info("正在取消任务...");
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
    } catch {
      toast.error("取消任务失败");
    }
  };

  const handleDelete = async (taskId: string) => {
    if (!novelId) return;
    if (!window.confirm("确定要删除此任务吗？此操作不可恢复。")) return;
    try {
      await batchDeleteTasks(novelId, [taskId]);
      toast.success("任务已删除");
      if (currentTaskId === taskId) {
        setTask(null);
      }
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
    } catch {
      toast.error("删除任务失败");
    }
  };

  const handleResume = (taskId: string) => {
    onResumeTask?.(taskId);
  };

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-2xl font-bold text-text">{title}</h1>

        {/* Task Selector + Panel (Combined) */}
        {novelId && (
          <div ref={panelRef} className="relative">
            <button
              type="button"
              onClick={() => setTaskPanelOpen(!taskPanelOpen)}
              disabled={tasksLoading}
              className={cn(
                "group flex h-9 items-center justify-between gap-2 rounded-md border border-border bg-transparent px-3 py-2 text-sm text-text shadow-sm transition-all",
                "hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-primary/50",
                "disabled:cursor-not-allowed disabled:opacity-50"
              )}
            >
              {tasksLoading ? (
                <span className="text-text-muted">加载中...</span>
              ) : tasks.length === 0 ? (
                <span className="text-text-muted">暂无任务</span>
              ) : currentTaskDisplay.id ? (
                <span className="flex items-center gap-2">
                  <span className="truncate font-mono text-xs">{currentTaskDisplay.id}</span>
                  {currentTaskDisplay.config && (
                    <Badge variant={currentTaskDisplay.config.variant} className="text-[10px] px-1.5 py-0">
                      {currentTaskDisplay.config.label}
                    </Badge>
                  )}
                </span>
              ) : (
                <span className="text-text-muted">选择任务</span>
              )}
              <ChevronDown
                className={cn(
                  "h-4 w-4 shrink-0 opacity-50 transition-transform duration-200",
                  taskPanelOpen && "rotate-180"
                )}
              />
            </button>

            <AnimatePresence>
              {taskPanelOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.15 }}
                  className="absolute left-0 top-full z-50 mt-2 w-96 rounded-lg border border-border bg-surface shadow-lg"
                >
                  <div className="p-3">
                    {/* Header with count and running indicator */}
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-sm font-medium text-text">分析任务</span>
                      <span className="rounded-full bg-surface-hover px-2 py-0.5 text-xs text-text-muted">
                        {tasks.length}
                      </span>
                      {runningCount > 0 && (
                        <span className="rounded-full bg-primary-subtle px-2 py-0.5 text-xs text-primary">
                          {runningCount} 运行中
                        </span>
                      )}
                    </div>

                    {/* Task List */}
                    <div className="max-h-72 space-y-0.5 overflow-y-auto">
                      {tasks.length === 0 ? (
                        <p className="py-4 text-center text-sm text-text-muted">
                          暂无分析任务
                        </p>
                      ) : (
                        tasks.map((task) => (
                          <TaskRow
                            key={task.task_id}
                            task={task}
                            isActive={currentTaskId === task.task_id}
                            onSelect={handleSelect}
                            onCancel={handleCancel}
                            onDelete={handleDelete}
                            onResume={handleResume}
                          />
                        ))
                      )}
                    </div>

                    {/* New Task Button */}
                    <div className="mt-3 border-t border-border pt-3">
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={onCreateTask}
                        disabled={isResuming}
                      >
                        <Plus className="mr-1 h-3.5 w-3.5" />
                        新建分析任务
                      </Button>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        <div className="ml-auto flex items-center gap-2">
          {onCreateTask && (
            <Button
              variant="outline"
              size="sm"
              onClick={onCreateTask}
              disabled={isResuming}
            >
              <Plus className={cn("h-3.5 w-3.5")} />
              新建分析
            </Button>
          )}
          {onDeleteCurrentTask && (
            <Button variant="ghost" size="sm" onClick={onDeleteCurrentTask}>
              <Trash2 className="h-3.5 w-3.5" />
              删除
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
