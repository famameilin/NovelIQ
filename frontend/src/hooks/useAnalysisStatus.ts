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
 * 任务: sse-architecture-review
 * 修改内容:
 * - 处理 stage_complete 事件，计算阶段耗时
 * - stage_start / stage_progress 重复逻辑提取为 _handleStageChange
 * - statusMap 增加 topic-model 独立文案
 * - 类型对齐：ErrorData 增加 stage 字段
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useSSEListener } from "./useEventSource";
import { useStreamStore } from "@/store/streamStore";
import { appConfig } from "@/config";
import { getAnalysisStatus } from "@/api/analysis";
import type {
  StreamMessageType,
  ProgressDetail,
  LLMOutputData,
  ErrorData,
} from "@/api/streamTypes";

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
    (data: ProgressDetail) => {
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
    (type: StreamMessageType, data: unknown) => {
      switch (type) {
        case "stage_start":
          _handleStageChange(data as ProgressDetail);
          // 记录阶段开始时间
          stageStartTimeRef.current = Date.now();
          break;

        case "stage_progress":
          _handleStageChange(data as ProgressDetail);
          break;

        case "stage_complete": {
          const stageData = data as ProgressDetail;
          // 计算并记录阶段耗时
          if (stageStartTimeRef.current && stageData.stage) {
            const duration = Date.now() - stageStartTimeRef.current;
            setStageDuration(stageData.stage, duration);
            stageStartTimeRef.current = null;
          }
          break;
        }

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
        const message = data as { type: StreamMessageType; task_id: string; data: unknown };
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
      stageStartTimeRef.current = null;

      getAnalysisStatus(novelId, taskId)
        .then((status) => {
          // 将 HTTP 返回的进度数据写入 streamStore，解决刷新后进度面板空白问题
          if (status.status === "running" && status.stage) {
            updateProgress({
              stage: status.stage,
              sub_stage: status.sub_stage ?? "",
              phase: status.sub_stage ?? "",
              current: status.current ?? 0,
              total: status.total ?? 0,
              percent: status.progress,
              message: status.message ?? "",
            });
          }

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
