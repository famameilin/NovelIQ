/**
 * useAnalysisStatus - 分析任务状态 Hook
 *
 * 创建时间: 2026-04-04
 * 创建者: GLM-5
 * 任务: 分析任务状态轮询
 * 说明: 通过 SSE 实时更新分析任务状态
 *
 * 修改时间: 2026-04-09
 * 创建者: GLM-5
 * 任务: refactor/sse-unified-event-bus
 * 修改内容:
 * - 适配统一 SSE 事件格式（StreamEventData）
 * - LLM 输出从 StreamEventData 读取 content/chunk_id/sub_stage
 * - HTTP backfill 适配 StreamEventData 字段
 */

import { useEffect, useRef, useState, useCallback } from "react";
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
  // 中文注释：HTTP backfill 需要对 pending/running/cancelling 做统一归一化，
  // 避免切换任务或刷新页面时沿用上一个任务留下来的旧进度面板状态。
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
    chunk_id: 0,
    current: status.current ?? 0,
    total: status.total ?? 0,
    percent: status.progress,
    sub_percent: 0,
    content: "",
    message: fallbackMessage,
  };
}

function isMockEnabled(): boolean {
  return (
    import.meta.env.DEV &&
    (appConfig.enableMock ||
      import.meta.env.VITE_ENABLE_MOCK === "true" ||
      new URLSearchParams(window.location.search).get("mock") === "true")
  );
}

/**
 * 修改时间: 2026-04-28
 * 修改者: Codex
 * 任务: 修复后台恢复后分析页卡死与白屏
 * 修改内容:
 * - 将同一 stream/action 的连续 LLM 输出合并进批量缓冲，避免后台恢复时逐 token 触发 store 更新。
 * - 让前台恢复只按“每流一次”回写，减少主线程渲染风暴。
 */
function buildLLMOutputBufferKey(data: Pick<StreamEventData, "action" | "stage" | "sub_stage" | "chunk_id" | "stream_id">): string {
  return [
    data.action,
    data.stage,
    data.sub_stage || "default",
    String(data.chunk_id ?? 0),
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
  } = useStreamStore();

  const enabled = !!novelId && !!taskId && (options?.enabled ?? true);
  const prevStatusRef = useRef<string | null>(null);
  const stageStartTimeRef = useRef<number | null>(null);
  const llmOutputBufferRef = useRef<Map<string, StreamEventData>>(new Map());
  const flushTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const hasConnectedOnceRef = useRef(false);
  const lastForegroundSyncAtRef = useRef(0);
  const [stableTaskId, setStableTaskId] = useState<string | null>(null);
  const sseReceivedMessageRef = useRef(false);
  const wsStable = !!taskId && stableTaskId === taskId;

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

  /**
   * 修改时间: 2026-04-28
   * 修改者: Codex
   * 任务: 修复后台恢复后分析页卡死与白屏
   * 修改内容:
   * - 后台标签页恢复后，任务状态必须允许重新回填，不能继续依赖“初始化时那一次”HTTP 查询。
   * - 终态回填也会同步更新 store，避免错过 task_complete/task_cancelled 事件后面板继续停在旧阶段。
   */
  const applyTaskStatusBackfill = useCallback(
    (status: TaskStatusResponse) => {
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
          chunk_id: 0,
          current: 0,
          total: 0,
          percent: 100,
          sub_percent: 0,
          content: "",
          message: "分析完成",
        });
        setError(null);
        if (prevStatusRef.current !== "completed") {
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
          chunk_id: 0,
          current: 0,
          total: 0,
          percent: 0,
          sub_percent: 0,
          content: "",
          message: "任务已取消",
        });
        setError(null);
        if (prevStatusRef.current !== "cancelled") {
          optionsRef.current?.onCancelled?.();
        }
        prevStatusRef.current = "cancelled";
        return;
      }

      if (status.status === "failed") {
        setError(status.error || "分析失败");
        if (prevStatusRef.current !== "failed") {
          optionsRef.current?.onFailed?.(status.error || "分析失败");
        }
        prevStatusRef.current = "failed";
      }
    },
    [setError, updateProgress],
  );

  /**
   * 修改时间: 2026-04-28
   * 修改者: Codex
   * 任务: 修复后台恢复后分析页卡死与白屏
   * 修改内容:
   * - 活跃任务状态同步收口成单独回调，供首次挂载、前台恢复、SSE 重连统一复用。
   * - 失败时仍显式暴露错误，避免后台恢复后无声卡死。
   */
  const syncTaskStatus = useCallback(() => {
    if (!novelId || !taskId) {
      return Promise.resolve();
    }

    return getTaskStatus(novelId, taskId)
      .then((status) => {
        applyTaskStatusBackfill(status);
      })
      .catch((error: unknown) => {
        // 中文注释：HTTP backfill 只是 SSE 的补偿路径，失败时不终止监听，但必须显式暴露错误。
        console.warn("Failed to backfill analysis task status", error);
        setError("任务状态同步失败，正在等待实时事件恢复");
      });
  }, [applyTaskStatusBackfill, novelId, setError, taskId]);

  /**
   * 修改时间: 2026-04-28
   * 修改者: Codex
   * 任务: 修复后台恢复后分析页卡死与白屏
   * 修改内容:
   * - LLM 输出先进入 ref 缓冲，按固定节奏批量刷入 Zustand。
   * - 这样浏览器前台恢复后即便瞬时补发大量 SSE，也不会逐条触发重渲染。
   */
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
      const bufferKey = buildLLMOutputBufferKey({
        action: eventData.action,
        stage: eventData.stage,
        sub_stage: eventData.sub_stage,
        chunk_id: eventData.chunk_id,
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
        });
      } else {
        llmOutputBufferRef.current.set(bufferKey, { ...eventData });
      }

      scheduleBufferedLLMFlush();
    },
    [scheduleBufferedLLMFlush],
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
          bufferLLMOutput({
            action: eventData.action,
            stage: eventData.stage,
            sub_stage: eventData.sub_stage,
            chunk_id: eventData.chunk_id,
            stream_id: eventData.stream_id,
            current: eventData.current,
            total: eventData.total,
            percent: eventData.percent,
            sub_percent: eventData.sub_percent,
            content: eventData.content,
            message: eventData.message,
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
            chunk_id: 0,
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
            chunk_id: 0,
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
      if (eventType === "message") {
        const message = data as { type: SSEEventType; task_id: string; data: unknown };
        if (message.task_id === taskId) {
          if (
            !sseReceivedMessageRef.current &&
            (message.type === "stage_start" ||
              message.type === "stage_progress" ||
              message.type === "llm_output" ||
              message.type === "llm_thinking")
          ) {
            sseReceivedMessageRef.current = true;
            setStableTaskId(taskId);
          }
          handleMessage(message.type, message.data);
        }
      } else {
        if (
          !sseReceivedMessageRef.current &&
          (eventType === "stage_start" ||
            eventType === "stage_progress" ||
            eventType === "llm_output" ||
            eventType === "llm_thinking")
        ) {
          sseReceivedMessageRef.current = true;
          setStableTaskId(taskId);
        }
        handleMessage(eventType as SSEEventType, data);
      }
    },
    onError: () => {
      setConnected(false);
      setStableTaskId(null);
      sseReceivedMessageRef.current = false;
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
      sseReceivedMessageRef.current = false;
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
  }, [taskId, novelId, setTaskId, reset, syncTaskStatus]);

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
    wsStable,
  };
}
