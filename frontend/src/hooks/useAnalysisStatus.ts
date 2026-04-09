/**
 * useAnalysisStatus - 分析任务状态 Hook
 *
 * 创建时间: 2026-04-04
 * 创建者: GLM-5
 * 任务: 分析任务状态轮询
 * 说明: 通过 SSE 实时更新分析任务状态
 *
 * 修改时间: 2026-04-09
 * 修改者: TraeAI
 * 任务: 前端适配 SSE
 * 修改内容: 将 WebSocket 替换为 SSE，支持事件类型监听
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { useSSEListener } from "./useEventSource";
import { useStreamStore } from "@/store/streamStore";
import { appConfig } from "@/config";
import { getAnalysisStatus } from "@/api/analysis";
import type { StreamMessage, StreamMessageType, ProgressDetail, LLMOutputData, ErrorData } from "@/api/streamTypes";

const SSE_URL = appConfig.apiBaseUrl;

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
    reset,
  } = useStreamStore();

  const enabled = !!novelId && !!taskId && (options?.enabled ?? true);
  const prevStatusRef = useRef<string | null>(null);
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

  const handleMessage = useCallback((type: StreamMessageType, data: unknown) => {
    const message: StreamMessage = {
      type,
      task_id: streamMessageOpts.current.taskId || "",
      data: data as StreamMessage["data"],
      timestamp: new Date().toISOString(),
    };

    const opts = streamMessageOpts.current;
    switch (message.type) {
      case "stage_start":
        updateProgress(data as ProgressDetail);
        if (opts.novelId && opts.taskId) {
          const stageData = data as ProgressDetail;
          const statusMap: Record<string, string> = {
            preprocess: "chunking",
            annotate: "annotating",
            aggregate: "aggregating",
            "topic-model": "aggregating",
            diagnose: "diagnosing",
          };
          const status = statusMap[stageData.stage] || stageData.stage;
          if (prevStatusRef.current !== status) {
            prevStatusRef.current = status;
            if (["pending", "running", "chunking", "annotating", "aggregating", "diagnosing", "cancelling"].includes(status)) {
              optionsRef.current?.onRunning?.();
            }
          }
        }
        break;
      case "stage_progress":
        updateProgress(data as ProgressDetail);
        if (opts.novelId && opts.taskId) {
          const stageData = data as ProgressDetail;
          const statusMap: Record<string, string> = {
            preprocess: "chunking",
            annotate: "annotating",
            aggregate: "aggregating",
            "topic-model": "aggregating",
            diagnose: "diagnosing",
          };
          const status = statusMap[stageData.stage] || stageData.stage;
          if (prevStatusRef.current === null && stageData.stage) {
            prevStatusRef.current = "annotating";
            optionsRef.current?.onRunning?.();
          } else if (prevStatusRef.current !== status) {
            prevStatusRef.current = status;
            if (["pending", "running", "chunking", "annotating", "aggregating", "diagnosing", "cancelling"].includes(status)) {
              optionsRef.current?.onRunning?.();
            }
          }
        }
        break;
      case "llm_output":
      case "llm_thinking":
        appendLLMOutput(data as LLMOutputData);
        break;
      case "task_error":
        setError((data as ErrorData).error);
        optionsRef.current?.onFailed?.((data as ErrorData).error || "未知错误");
        break;
      case "task_cancelled":
        updateProgress({
          stage: "cancelled",
          sub_stage: "",
          current: 0,
          total: 0,
          percent: 0,
          message: "任务已取消",
        });
        setError(null);
        optionsRef.current?.onCancelled?.();
        break;
      case "task_complete":
        updateProgress({
          stage: "completed",
          sub_stage: "",
          current: 0,
          total: 0,
          percent: 100,
          message: "分析完成",
        });
        optionsRef.current?.onCompleted?.();
        break;
    }
  }, [updateProgress, appendLLMOutput, setError]);

  const sseUrl = enabled && !!taskId && !isMockEnabled()
    ? `${SSE_URL}/api/events/tasks/${taskId}`
    : null;

  const { isConnected, disconnect } = useSSEListener(sseUrl, {
    onEvent: (eventType, data) => {
      if (eventType === "message") {
        const message = data as StreamMessage;
        if (message.task_id === taskId) {
          if (!sseReceivedMessageRef.current && (message.type === "stage_start" || message.type === "stage_progress" || message.type === "llm_output" || message.type === "llm_thinking")) {
            sseReceivedMessageRef.current = true;
            setWsStable(true);
          }
          handleMessage(message.type, message.data);
        }
      } else {
        if (!sseReceivedMessageRef.current && (eventType === "stage_start" || eventType === "stage_progress" || eventType === "llm_output" || eventType === "llm_thinking")) {
          sseReceivedMessageRef.current = true;
          setWsStable(true);
        }
        handleMessage(eventType as StreamMessageType, data);
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

      getAnalysisStatus(novelId, taskId)
        .then((status) => {
          if (status.status === "running") {
            optionsRef.current?.onRunning?.();
            prevStatusRef.current = "running";
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
        .catch(() => {});
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
