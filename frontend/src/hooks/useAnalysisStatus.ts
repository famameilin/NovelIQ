/** 通过 SSE 和 HTTP backfill 同步分析任务状态 */

import { useEffect, useRef, useCallback } from "react";
import { useSSEListener } from "./useEventSource";
import { useStreamStore } from "@/store/streamStore";
import { appConfig } from "@/config";
import { getTaskStatus } from "@/api/analysis";
import type {
  SSEEventType,
  StreamEventData,
  ErrorData,
} from "@/api/streamTypes";
import type { TaskStatusResponse } from "@/api/types";

const SSE_URL = appConfig.apiBaseUrl;

function buildBackfillProgress(status: TaskStatusResponse): StreamEventData {
  // HTTP backfill 需要对 pending/running/cancelling 做统一归一化，
  // 避免切换任务或刷新页面时沿用上一个任务留下来的旧进度面板状态
  const fallbackStage =
    status.stage ??
    (status.status === "pending"
      ? "preprocess"
      : status.status === "cancelling"
        ? "cancelling"
        : "");
  const fallbackMessage =
    status.message ??
    (status.status === "pending"
      ? "任务待执行"
      : status.status === "cancelling"
        ? "任务取消中"
        : "任务执行中");

  return {
    action: status.status === "pending" ? "start" : "progress",
    stage: fallbackStage,
    sub_stage: status.sub_stage ?? "",
    // 2026-08-15 M5：HTTP 回填不携带真实章节，不得覆写成 0——
    // updateProgress 对缺失 chapter_id 保留旧值，避免 annotate 期间面板按章匹配落空
    current: status.current ?? 0,
    total: status.total ?? 0,
    percent: status.progress,
    sub_percent: 0,
    content: "",
    message: fallbackMessage,
  };
}

function isMockEnabled(): boolean {
  const mockWorkerActive =
    typeof navigator !== "undefined" && navigator.serviceWorker?.controller != null;
  return (
    import.meta.env.DEV &&
    (appConfig.enableMock ||
      import.meta.env.VITE_ENABLE_MOCK === "true" ||
      new URLSearchParams(window.location.search).get("mock") === "true" ||
      mockWorkerActive)
  );
}

/** 将同一流的连续输出合并进批量缓冲，减少后台恢复后的逐 token 刷新 */
function buildLLMOutputBufferKey(data: Pick<StreamEventData, "action" | "stage" | "sub_stage" | "chapter_id" | "stream_id">): string {
  return [
    data.action,
    data.stage,
    data.sub_stage || "default",
    String(data.chapter_id ?? 0),
    data.stream_id || "default",
  ].join("|");
}

export interface UseAnalysisStatusOptions {
  enabled?: boolean;
  onRunning?: () => void;
  onCompleted?: () => void;
  onCancelled?: () => void;
  onFailed?: (error: string) => void;
}

interface ApplyTaskStatusBackfillOptions {
  notifyTerminalCallbacks: boolean;
}

export function useAnalysisStatus(
  novelId: string | null,
  taskId: string | null,
  options?: UseAnalysisStatusOptions,
) {
  const {
    setConnected,
    setTaskId,
    updateProgress,
    appendLLMOutput,
    setError,
    setStageDuration,
    reset,
    resumeEpoch,
  } = useStreamStore();

  const enabled = !!novelId && !!taskId && (options?.enabled ?? true);
  const prevStatusRef = useRef<string | null>(null);
  const stageStartTimeRef = useRef<number | null>(null);
  const llmOutputBufferRef = useRef<Map<string, StreamEventData>>(new Map());
  const flushTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const hasConnectedOnceRef = useRef(false);
  const hasHydratedTaskStatusRef = useRef(false);
  const lastForegroundSyncAtRef = useRef(0);

  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const streamMessageOpts = useRef({ novelId, taskId });
  useEffect(() => {
    streamMessageOpts.current = { novelId, taskId };
  }, [novelId, taskId]);

  /** 处理阶段变化（stage_start / stage_progress 共用） */
  const _handleStageChange = useCallback(
    (data: StreamEventData) => {
      updateProgress(data);
      const opts = streamMessageOpts.current;
      if (!opts.novelId || !opts.taskId) return;

      // 阶段变化时触发 onRunning 回调
      if (prevStatusRef.current !== data.stage) {
        prevStatusRef.current = data.stage;
        optionsRef.current?.onRunning?.();
      }
    },
    [updateProgress],
  );

  /** 后台标签页恢复后，允许重新回填任务状态并同步终态 */
  const applyTaskStatusBackfill = useCallback(
    (status: TaskStatusResponse, options: ApplyTaskStatusBackfillOptions) => {
      if (status.status === "pending" || status.status === "running" || status.status === "cancelling") {
        updateProgress(buildBackfillProgress(status));
        setError(null);
        if (prevStatusRef.current !== status.status) {
          optionsRef.current?.onRunning?.();
        }
        prevStatusRef.current = status.status;
        return;
      }

      if (status.status === "completed") {
        updateProgress({
          action: "complete",
          stage: "completed",
          sub_stage: "",
          current: 0,
          total: 0,
          percent: 100,
          sub_percent: 0,
          content: "",
          message: "分析完成",
        });
        setError(null);
        if (options.notifyTerminalCallbacks && prevStatusRef.current !== "completed") {
          optionsRef.current?.onCompleted?.();
        }
        prevStatusRef.current = "completed";
        return;
      }

      if (status.status === "cancelled") {
        updateProgress({
          action: "complete",
          stage: "cancelled",
          sub_stage: "",
          current: 0,
          total: 0,
          percent: 0,
          sub_percent: 0,
          content: "",
          message: "任务已取消",
        });
        setError(null);
        if (options.notifyTerminalCallbacks && prevStatusRef.current !== "cancelled") {
          optionsRef.current?.onCancelled?.();
        }
        prevStatusRef.current = "cancelled";
        return;
      }

      if (status.status === "failed") {
        setError(status.error || "分析失败");
        if (options.notifyTerminalCallbacks && prevStatusRef.current !== "failed") {
          optionsRef.current?.onFailed?.(status.error || "分析失败");
        }
        prevStatusRef.current = "failed";
      }
    },
    [setError, updateProgress],
  );

  /** 首次挂载、前台恢复和 SSE 重连都复用同一套活跃任务状态回填逻辑 */
  const syncTaskStatus = useCallback(() => {
    if (!novelId || !taskId) {
      return Promise.resolve();
    }

    const notifyTerminalCallbacks = hasHydratedTaskStatusRef.current;
    return getTaskStatus(novelId, taskId)
      .then((status) => {
        applyTaskStatusBackfill(status, { notifyTerminalCallbacks });
        hasHydratedTaskStatusRef.current = true;
      })
      .catch((error: unknown) => {
        // HTTP backfill 只是 SSE 的补偿路径，失败时不终止监听，但必须显式暴露错误
        console.warn("Failed to backfill analysis task status", error);
        setError("任务状态同步失败，正在等待实时事件恢复");
      });
  }, [applyTaskStatusBackfill, novelId, setError, taskId]);

  /** LLM 输出先进入 ref 缓冲，再按固定节奏批量刷入 Zustand */
  const flushBufferedLLMOutputs = useCallback(() => {
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }

    if (llmOutputBufferRef.current.size === 0) {
      return;
    }

    const bufferedMessages = Array.from(llmOutputBufferRef.current.values());
    llmOutputBufferRef.current.clear();
    bufferedMessages.forEach((message) => {
      appendLLMOutput(message);
    });
  }, [appendLLMOutput]);

  const scheduleBufferedLLMFlush = useCallback(() => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      return;
    }
    if (flushTimerRef.current !== null) {
      return;
    }

    flushTimerRef.current = window.setTimeout(() => {
      flushBufferedLLMOutputs();
    }, appConfig.llmOutputFlushIntervalMs);
  }, [flushBufferedLLMOutputs]);

  const bufferLLMOutput = useCallback(
    (eventData: StreamEventData) => {
      // tool_call 事件按工具独立成行，且需要 started→success/failed 状态转移；
      // 不参与按内容拼接的批处理缓冲（同窗口多个工具会拼成假工具名），直接刷入 store
      if (eventData.action === "tool_call") {
        appendLLMOutput({ ...eventData, status: eventData.status ?? "started" });
        return;
      }
      const bufferKey = buildLLMOutputBufferKey({
        action: eventData.action,
        stage: eventData.stage,
        sub_stage: eventData.sub_stage,
        chapter_id: eventData.chapter_id,
        stream_id: eventData.stream_id,
      });
      const existing = llmOutputBufferRef.current.get(bufferKey);
      if (existing) {
        llmOutputBufferRef.current.set(bufferKey, {
          ...existing,
          current: eventData.current,
          total: eventData.total,
          percent: eventData.percent,
          sub_percent: eventData.sub_percent,
          content: existing.content + eventData.content,
          message: eventData.message,
          status: eventData.status ?? existing.status,
        });
      } else {
        llmOutputBufferRef.current.set(bufferKey, { ...eventData });
      }

      scheduleBufferedLLMFlush();
    },
    [appendLLMOutput, scheduleBufferedLLMFlush],
  );

  const handleMessage = useCallback(
    (type: SSEEventType, data: unknown) => {
      const eventData = data as StreamEventData;

      switch (type) {
        case "stage_start":
          _handleStageChange(eventData);
          // 记录阶段开始时间
          stageStartTimeRef.current = Date.now();
          break;

        case "stage_progress":
          _handleStageChange(eventData);
          break;

        case "stage_complete": {
          // 计算并记录阶段耗时
          if (stageStartTimeRef.current && eventData.stage) {
            const duration = Date.now() - stageStartTimeRef.current;
            setStageDuration(eventData.stage, duration);
            stageStartTimeRef.current = null;
          }
          break;
        }

        case "llm_output":
        case "llm_thinking":
        case "tool_call":
          bufferLLMOutput({
            action: eventData.action,
            stage: eventData.stage,
            sub_stage: eventData.sub_stage,
            chapter_id: eventData.chapter_id,
            stream_id: eventData.stream_id,
            current: eventData.current,
            total: eventData.total,
            percent: eventData.percent,
            sub_percent: eventData.sub_percent,
            content: eventData.content,
            message: eventData.message,
            status: eventData.status ?? null,
          });
          break;

        case "task_error":
          flushBufferedLLMOutputs();
          setError((data as ErrorData).error);
          prevStatusRef.current = "failed";
          optionsRef.current?.onFailed?.((data as ErrorData).error || "未知错误");
          break;

        case "task_cancelled":
          flushBufferedLLMOutputs();
          updateProgress({
            action: "complete",
            stage: "cancelled",
            sub_stage: "",
            current: 0,
            total: 0,
            percent: 0,
            sub_percent: 0,
            content: "",
            message: "任务已取消",
          });
          setError(null);
          prevStatusRef.current = "cancelled";
          optionsRef.current?.onCancelled?.();
          break;

        case "task_complete":
          flushBufferedLLMOutputs();
          updateProgress({
            action: "complete",
            stage: "completed",
            sub_stage: "",
            current: 0,
            total: 0,
            percent: 100,
            sub_percent: 0,
            content: "",
            message: "分析完成",
          });
          prevStatusRef.current = "completed";
          optionsRef.current?.onCompleted?.();
          break;
      }
    },
    [bufferLLMOutput, flushBufferedLLMOutputs, _handleStageChange, setError, setStageDuration, updateProgress],
  );

  const sseUrl =
    enabled && !!taskId && !isMockEnabled()
      ? `${SSE_URL}/api/events/tasks/${taskId}`
      : null;

  const { isConnected, disconnect } = useSSEListener(sseUrl, {
    onEvent: (eventType, data) => {
      // 2026-08-12: 后端 SSE 消息格式为 { type, data }，不含 task_id 字段；
      // 移除恒为 false 的 task_id 过滤，message 事件直接按内部类型分发
      if (eventType === "message") {
        const message = data as { type: SSEEventType; data: unknown };
        handleMessage(message.type, message.data);
      } else {
        handleMessage(eventType as SSEEventType, data);
      }
    },
    onError: () => {
      setConnected(false);
    },
  });

  useEffect(() => {
    if (isConnected) {
      setConnected(true);
      flushBufferedLLMOutputs();
      if (hasConnectedOnceRef.current && enabled) {
        void syncTaskStatus();
      }
      hasConnectedOnceRef.current = true;
    }
  }, [enabled, flushBufferedLLMOutputs, isConnected, setConnected, syncTaskStatus]);

  useEffect(() => {
    if (taskId && novelId) {
      setTaskId(taskId);
      prevStatusRef.current = null;
      hasHydratedTaskStatusRef.current = false;
      stageStartTimeRef.current = null;
      hasConnectedOnceRef.current = false;
      llmOutputBufferRef.current.clear();
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }

      void syncTaskStatus();
    } else if (!taskId) {
      llmOutputBufferRef.current.clear();
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      reset();
    }
    // 2026-08-14 D5：resumeEpoch 变化（同 task_id resume 开新轮）时同样重置
    // 内部缓冲，避免旧轮 LLM 输出/进度状态与新轮混叠
  }, [taskId, novelId, setTaskId, reset, syncTaskStatus, resumeEpoch]);

  // 浏览器后台期间 EventSource 可能保持连接（不触发重连），
  // 前台恢复时主动 flush 缓冲并做一次 HTTP 状态回填，避免进度/终态陈旧
  useEffect(() => {
    if (!enabled) {
      return;
    }

    const handleForegroundResume = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return;
      }

      const now = Date.now();
      if (now - lastForegroundSyncAtRef.current < 300) {
        return;
      }
      lastForegroundSyncAtRef.current = now;

      flushBufferedLLMOutputs();
      void syncTaskStatus();
    };

    document.addEventListener("visibilitychange", handleForegroundResume);
    window.addEventListener("focus", handleForegroundResume);
    return () => {
      document.removeEventListener("visibilitychange", handleForegroundResume);
      window.removeEventListener("focus", handleForegroundResume);
    };
  }, [enabled, flushBufferedLLMOutputs, syncTaskStatus]);

  useEffect(() => {
    return () => {
      flushBufferedLLMOutputs();
      disconnect();
    };
  }, [disconnect, flushBufferedLLMOutputs]);

  return {
    isConnected,
  };
}
