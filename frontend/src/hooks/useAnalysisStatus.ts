/** 同步任务状态并接收真实模型通信 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSSEListener } from "./useEventSource";
import { useStreamStore } from "@/store/streamStore";
import { appConfig } from "@/config";
import { getTaskStatus } from "@/api/analysis";
import type { SSEEventType, StreamEventData } from "@/api/streamTypes";
import type { TaskStatus } from "@/api/types";
export interface UseAnalysisStatusOptions {
  enabled?: boolean; onRunning?: () => void; onCompleted?: () => void;
  onCancelled?: () => void; onFailed?: (error: string) => void;
}
export function useAnalysisStatus(novelId: string | null, taskId: string | null, options?: UseAnalysisStatusOptions) {
  const queryClient = useQueryClient();
  const setTaskId = useStreamStore((s) => s.setTaskId);
  const setStatus = useStreamStore((s) => s.setStatus);
  const setError = useStreamStore((s) => s.setError);
  const append = useStreamStore((s) => s.appendLLMOutput);
  const setConnected = useStreamStore((s) => s.setConnected);
  const epoch = useStreamStore((s) => s.resumeEpoch);
  const [active, setActive] = useState(false);
  const callbacks = useRef(options);
  const previous = useRef<TaskStatus | null>(null);
  const enabled = !!novelId && !!taskId && (options?.enabled ?? true);
  useEffect(() => { callbacks.current = options; }, [options]);
  const apply = useCallback((status: TaskStatus, notify: boolean) => {
    setStatus(status);
    setActive(status === "pending" || status === "running");
    if (notify && previous.current !== status) {
      if (status === "running") callbacks.current?.onRunning?.();
      if (status === "completed") callbacks.current?.onCompleted?.();
      if (status === "cancelled") callbacks.current?.onCancelled?.();
      if (status === "failed") callbacks.current?.onFailed?.("分析失败");
    }
    previous.current = status;
  }, [setStatus]);
  useEffect(() => {
    let disposed = false;
    previous.current = null;
    setTaskId(taskId);
    if (!enabled || !novelId || !taskId) return;
    const sync = () => getTaskStatus(novelId, taskId).then((data) => {
      if (!disposed) { apply(data.status, previous.current !== null); setError(null); }
    }).catch(() => { if (!disposed) setError("任务状态同步失败"); });
    void sync();
    const timer = window.setInterval(() => { void sync(); }, 5000);
    const foreground = () => { if (document.visibilityState !== "hidden") void sync(); };
    window.addEventListener("focus", foreground);
    document.addEventListener("visibilitychange", foreground);
    return () => { disposed = true; window.clearInterval(timer); window.removeEventListener("focus", foreground); document.removeEventListener("visibilitychange", foreground); };
  }, [novelId, taskId, enabled, epoch, setTaskId, apply, setError]);
  const handle = (type: SSEEventType, data: unknown) => {
    if (type === "message") { const nested = data as {type: SSEEventType; data: unknown}; handle(nested.type, nested.data); return; }
    if (type === "llm_output" || type === "llm_thinking" || type === "tool_call") append(data as StreamEventData);
    if (type === "task_complete" || type === "task_error" || type === "task_cancelled") {
      const status = type === "task_complete" ? "completed" : type === "task_error" ? "failed" : "cancelled";
      apply(status, true);
      setError(status === "failed" ? "分析失败" : null);
      void queryClient.invalidateQueries({queryKey: ["pipeline", novelId, taskId]});
    }
  };
  const {isConnected} = useSSEListener(enabled && active ? `${appConfig.apiBaseUrl}/api/novels/${novelId}/events/tasks/${taskId}` : null, {onEvent: (type, data) => handle(type as SSEEventType, data)});
  useEffect(() => { setConnected(isConnected); }, [isConnected, setConnected]);
  return {isConnected};
}
