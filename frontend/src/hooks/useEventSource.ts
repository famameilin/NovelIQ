/** SSE 连接管理 Hook，提供事件监听和浏览器原生自动重连 */

import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";

export type SSEEventType =
  | "stage_start"
  | "stage_progress"
  | "stage_complete"
  | "llm_output"
  | "llm_thinking"
  | "tool_call"
  | "task_complete"
  | "task_error"
  | "task_cancelled"
  | "work_reset"
  | "task_reset"
  | "chapter_reset"
  | "pipeline_progress"
  | "reconnect_required"
  | "message";

interface SSEEventListenerOptions {
  onEvent?: (eventType: SSEEventType, data: unknown) => void;
  onError?: (error: Event) => void;
  eventTypes?: SSEEventType[];
}

/** 从 canonical SSE 路径中提取 task_id */
function extractTaskIdFromUrl(url: string): string | null {
  const pathMatch = url.match(/\/tasks\/([^/?#]+)/);
  if (pathMatch) {
    return decodeURIComponent(pathMatch[1]);
  }
  throw new Error("SSE URL 必须使用 /tasks/{task_id} 路径");
}

// 每 task 最近一条 SSE 消息 id（seq）的持久化：模块级生命周期与 SPA 相同，
// 路由重挂载时带 last_seq 只回放增量，整页刷新后走全量回放（后端 ≤256 条缓冲）以重建页面历史
const lastSeqByTask = new Map<string, string>();

/** 测试辅助：清空持久化的 last_seq 状态 */
export function resetSSELastSeqForTesting(): void {
  lastSeqByTask.clear();
}

export function useSSEListener(
  url: string | null,
  options: SSEEventListenerOptions = {}
) {
  const { eventTypes } = options;
  const eventSourceRef = useRef<EventSource | null>(null);
  // 去重状态放在模块级 lastSeqByTask（按 task_id 分键），见文件顶部注释
  const [isConnected, setIsConnected] = useState(false);

  const emitEvent = useEffectEvent((eventType: SSEEventType, data: unknown) => {
    options.onEvent?.(eventType, data);
  });
  const emitError = useEffectEvent((error: Event) => {
    options.onError?.(error);
  });

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setIsConnected(false);
    // lastSeqByTask 有意不清空：跨重建保留，供下次连接去重回放
  }, []);

  useEffect(() => {
    if (!url) return;

    // 按 task_id 从模块级 Map 读取最近 seq（无则全量回放）；每 task_id 的 seq 单调递增，
    // 跨任务自然分键。浏览器原生自动重连携带 Last-Event-ID 头，优先于 query 中的 last_seq
    const taskId = extractTaskIdFromUrl(url);
    // 读取 Map 而非放进依赖：last_seq 更新不应重建连接
    const lastEventId = taskId ? (lastSeqByTask.get(taskId) ?? "") : "";
    const separator = url.includes("?") ? "&" : "?";
    const sseUrl = lastEventId ? `${url}${separator}last_seq=${encodeURIComponent(lastEventId)}` : url;

    const eventSource = new EventSource(sseUrl);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      setIsConnected(true);
    };

    // 不在 onerror 中主动 close，让浏览器原生自动重连
    eventSource.onerror = (error: Event) => {
      setIsConnected(false);
      emitError(error);
    };

    const defaultEventTypes: SSEEventType[] = [
      "stage_start",
      "stage_progress",
      "stage_complete",
      "llm_output",
      "llm_thinking",
      "tool_call",
      "task_complete",
      "task_error",
      "task_cancelled",
      "work_reset",
      "task_reset",
      "chapter_reset",
      "pipeline_progress",
      "reconnect_required",
      "message",
    ];

    const typesToListen = eventTypes || defaultEventTypes;

    for (const eventType of typesToListen) {
      eventSource.addEventListener(eventType, (event: MessageEvent) => {
        // 只记录非空的 lastEventId（后端按序发送 id: 字段）
        if (event.lastEventId && taskId) {
          const previous = Number(lastSeqByTask.get(taskId) ?? 0);
          if (Number(event.lastEventId) <= previous) return;
          lastSeqByTask.set(taskId, event.lastEventId);
        }
        let data: unknown;
        try {
          data = JSON.parse(event.data as string);
        } catch {
          data = event.data;
        }
        emitEvent(eventType as SSEEventType, data);
      });
    }

    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [url, eventTypes]);

  return {
    isConnected,
    disconnect,
  };
}
