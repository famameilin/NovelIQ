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
  const [wsStable, setWsStable] = useState(false);
  const sseReceivedMessageRef = useRef(false);

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
          // 统一格式：LLM 输出也从 StreamEventData 读取
          appendLLMOutput({
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
          setError((data as ErrorData).error);
          optionsRef.current?.onFailed?.((data as ErrorData).error || "未知错误");
          break;

        case "task_cancelled":
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
          optionsRef.current?.onCancelled?.();
          break;

        case "task_complete":
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
          optionsRef.current?.onCompleted?.();
          break;
      }
    },
    [_handleStageChange, appendLLMOutput, setError, setStageDuration, updateProgress],
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
            setWsStable(true);
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
          setWsStable(true);
        }
        handleMessage(eventType as SSEEventType, data);
      }
    },
    onError: () => {
      setConnected(false);
      setWsStable(false);
      sseReceivedMessageRef.current = false;
    },
  });

  useEffect(() => {
    if (isConnected) {
      setConnected(true);
    }
  }, [isConnected, setConnected]);

  useEffect(() => {
    if (taskId && novelId) {
      setTaskId(taskId);
      prevStatusRef.current = null;
      sseReceivedMessageRef.current = false;
      setWsStable(false);
      stageStartTimeRef.current = null;

      getTaskStatus(novelId, taskId)
        .then((status) => {
          // 中文注释：pending/cancelling 也是当前选中的活跃任务，需要显式覆盖旧进度并恢复“分析中”UI。
          if (status.status === "pending" || status.status === "running" || status.status === "cancelling") {
            updateProgress(buildBackfillProgress(status));
            optionsRef.current?.onRunning?.();
            prevStatusRef.current = status.status;
          } else if (status.status === "completed") {
            optionsRef.current?.onCompleted?.();
            prevStatusRef.current = "completed";
          } else if (status.status === "cancelled") {
            optionsRef.current?.onCancelled?.();
            prevStatusRef.current = "cancelled";
          } else if (status.status === "failed") {
            optionsRef.current?.onFailed?.(status.error || "分析失败");
            prevStatusRef.current = "failed";
          }
        })
        .catch((error: unknown) => {
          // 中文注释：HTTP backfill 只是 SSE 的补偿路径，失败时不终止监听，但必须显式暴露错误。
          console.warn("Failed to backfill analysis task status", error);
          setError("任务状态同步失败，正在等待实时事件恢复");
        });
    } else if (!taskId) {
      reset();
    }
  }, [taskId, novelId, setTaskId, reset]);

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    isConnected,
    wsStable,
  };
}
