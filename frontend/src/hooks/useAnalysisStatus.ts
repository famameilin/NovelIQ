/** 统一协调任务状态：状态以状态接口为源，进度流只在未收口时连接 */
import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSSEListener } from "./useEventSource";
import { useStreamStore } from "@/store/streamStore";
import { appConfig } from "@/config";
import { getTaskStatus } from "@/api/analysis";
import type { SSEEventType } from "@/api/streamTypes";
import type { TaskStatus } from "@/api/types";

const TERMINAL_STATUSES = ["completed", "failed", "cancelled"];

function isTerminalStatus(status: string): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export interface UseAnalysisStatusOptions {
  enabled?: boolean; onRunning?: () => void; onCompleted?: () => void;
  onCancelled?: () => void; onFailed?: (error: string) => void;
}
export function useAnalysisStatus(novelId: string | null, taskId: string | null, options?: UseAnalysisStatusOptions) {
  const client = useQueryClient();
  const projection = useStreamStore(s => s.projection);
  const epoch = useStreamStore(s => s.resumeEpoch);
  const currentTask = useStreamStore(s => s.currentTaskId);
  const callbacks = useRef(options);
  const previous = useRef<TaskStatus | null>(null);
  const enabled = !!novelId && !!taskId && (options?.enabled ?? true);
  useEffect(() => { callbacks.current = options; }, [options]);
  useEffect(() => {
    previous.current = null;
    useStreamStore.getState().setTaskId(taskId);
  }, [taskId]);
  const query = useQuery({
    queryKey: ["task-status", novelId, taskId], queryFn: () => getTaskStatus(novelId!, taskId!),
    enabled, staleTime: 5000,
    refetchInterval: query => isTerminalStatus(query.state.data?.status ?? "") ? false : 5000,
  });
  const handle = (type: SSEEventType, data: unknown, seq?: number) => {
    if (type === "message") {
      const nested = data as {type: SSEEventType; data: unknown}; handle(nested.type, nested.data, seq); return;
    }
    const store = useStreamStore.getState();
    store.applyNotice(taskId!, type, data, seq);
    const status = useStreamStore.getState().projection.status;
    if (status && ["snapshot", "task_state", "task_reset", "task_complete", "task_error", "task_cancelled"].includes(type)) {
      store.setStatus(status);
      // 任务状态只以状态接口为源，终态事件触发立即核对而不是直接改写缓存
      if (isTerminalStatus(status)) {
        void query.refetch();
        void client.invalidateQueries({queryKey: ["tasks", novelId]});
      }
    }
  };
  const httpStatus = query.data?.status;
  const httpTerminal = !!httpStatus && isTerminalStatus(httpStatus);
  // 先读取库状态再决定是否连接进度流：终态任务不进进度页也不订阅
  const url = enabled && currentTask === taskId && !!httpStatus && !httpTerminal && !(query.isError && !query.data)
    ? `${appConfig.apiBaseUrl}/api/novels/${novelId}/events/tasks/${taskId}?connection=${epoch}` : null;
  const {isConnected} = useSSEListener(url, {onEvent: handle});
  useEffect(() => { useStreamStore.getState().setConnected(isConnected); }, [isConnected]);
  const status = httpStatus ?? (currentTask === taskId ? projection.status : null) ?? null;
  useEffect(() => {
    if (!status) return;
    useStreamStore.getState().setStatus(status);
    if (previous.current && previous.current !== status) {
      if (status === "running") callbacks.current?.onRunning?.();
      if (status === "completed") callbacks.current?.onCompleted?.();
      if (status === "cancelled") callbacks.current?.onCancelled?.();
      if (status === "failed") callbacks.current?.onFailed?.(projection.error || "分析失败");
    }
    previous.current = status;
  }, [status, projection.error]);
  return {isConnected, status, query};
}
