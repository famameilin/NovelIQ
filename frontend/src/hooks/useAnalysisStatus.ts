/** 统一协调任务状态，终态核对与展示同步分别处理 */
import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSSEListener } from "./useEventSource";
import { useStreamStore } from "@/store/streamStore";
import { appConfig } from "@/config";
import { getTaskStatus } from "@/api/analysis";
import type { SSEEventType } from "@/api/streamTypes";
import type { AnalysisTask, TaskStatus } from "@/api/types";

export interface UseAnalysisStatusOptions {
  enabled?: boolean; onRunning?: () => void; onCompleted?: () => void;
  onCancelled?: () => void; onFailed?: (error: string) => void;
}
export function useAnalysisStatus(novelId: string | null, taskId: string | null, options?: UseAnalysisStatusOptions) {
  const client = useQueryClient();
  const projection = useStreamStore(s => s.projection);
  const snapshotReady = useStreamStore(s => s.snapshotReady);
  const epoch = useStreamStore(s => s.resumeEpoch);
  const connected = useStreamStore(s => s.isConnected);
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
    refetchInterval: query => connected || ["completed", "failed", "cancelled"].includes(query.state.data?.status ?? "") ? false : 5000,
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
      if (query.data) client.setQueryData(["task-status", novelId, taskId], {...query.data, status});
      client.setQueryData<AnalysisTask[]>(["tasks", novelId], tasks => tasks?.map(task =>
        task.task_id === taskId ? {...task, status} : task));
    }
  };
  // 有效任务首次打开总取快照，cancelling 和终态也不能跳过
  const projectionSynced = currentTask === taskId && snapshotReady && !projection.sync_pending
    && (projection.status === "completed" || (projection.status === null && projection.cursor === 0));
  const url = enabled && currentTask === taskId && !(query.isError && !query.data)
    && !(projectionSynced && query.data?.status === "completed")
    ? `${appConfig.apiBaseUrl}/api/novels/${novelId}/events/tasks/${taskId}?connection=${epoch}` : null;
  const {isConnected} = useSSEListener(url, {onEvent: handle});
  useEffect(() => { useStreamStore.getState().setConnected(isConnected); }, [isConnected]);
  const httpStatus = query.data?.status;
  const httpTerminal = httpStatus && ["completed", "failed", "cancelled"].includes(httpStatus);
  const status = (!connected && httpTerminal ? httpStatus : null) || (currentTask === taskId && projection.status) || httpStatus || null;
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
  return {isConnected, status, query, snapshotReady: currentTask === taskId && snapshotReady, projectionSynced};
}
