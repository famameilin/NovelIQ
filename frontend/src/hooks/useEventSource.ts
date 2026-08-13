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
  | "message";

interface SSEEventListenerOptions {
  onEvent?: (eventType: SSEEventType, data: unknown) => void;
  onError?: (error: Event) => void;
  eventTypes?: SSEEventType[];
}

/**
 * 从 url 中提取 task_id：优先匹配后端 SSE 路由 `/api/events/tasks/{taskId}` 的路径段，
 * 兼容把 task_id 放在 query 上的调用方（测试/其他宿主）。
 */
function extractTaskIdFromUrl(url: string): string | null {
  const pathMatch = url.match(/\/tasks\/([^/?#]+)/);
  if (pathMatch) {
    return decodeURIComponent(pathMatch[1]);
  }
  const queryIndex = url.indexOf("?");
  if (queryIndex >= 0) {
    return new URLSearchParams(url.slice(queryIndex)).get("task_id");
  }
  return null;
}

export function useSSEListener(
  url: string | null,
  options: SSEEventListenerOptions = {}
) {
  const { eventTypes } = options;
  const eventSourceRef = useRef<EventSource | null>(null);
  // 2026-08-12: 记录最近一条 SSE 消息的 id（后端契约：每 task_id 单调递增 seq）。
  // 浏览器原生自动重连会通过 Last-Event-ID 头续传，但组件重挂载/url 变化重建
  // EventSource 时不会带该头，这里把 last_seq 作为 query 传给后端只回放增量。
  const lastEventIdRef = useRef("");
  // 2026-08-13 P1-1: 记录上一次连接的 task_id。只有 task_id 变化（新任务流）才允许
  // 清空 last_seq；同一任务下 effect 重建（组件重挂载/StrictMode 双挂载/eventTypes
  // 变化）保留 lastEventIdRef，重建连接时携带 last_seq 只回放增量，避免 LLM 输出
  // 重复、进度回退。组件真正卸载后 ref 随实例销毁（页面级无持久化），StrictMode
  // 双挂载与同实例重建均在此覆盖。
  const lastTaskIdRef = useRef<string | null>(null);
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
    // lastEventIdRef 有意不清空：跨重建保留，供下次连接去重回放
  }, []);

  useEffect(() => {
    if (!url) return;

    // 2026-08-13 P1-1: 只在 url 的 task_id 变化（切换新任务流）时清空 last_seq。
    // 后端契约是每 task_id 的 seq 单调递增，跨任务携带旧 last_seq 会让新任务的
    // 早期事件被 event_manager 按 seq 过滤跳过（跨任务串流）。同一任务下 effect
    // 重建（组件重挂载/StrictMode 双挂载）保留 lastEventIdRef，重建 EventSource
    // 时把 last_seq 拼到 query，后端只回放增量。浏览器原生自动重连（同一
    // EventSource 对象）走 Last-Event-ID 头，不受本逻辑影响。
    const taskId = extractTaskIdFromUrl(url);
    if (taskId !== lastTaskIdRef.current) {
      lastEventIdRef.current = "";
      lastTaskIdRef.current = taskId;
    }

    // 读取 ref 而非放进依赖：lastEventId 更新不应重建连接
    const lastEventId = lastEventIdRef.current;
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
      "message",
    ];

    const typesToListen = eventTypes || defaultEventTypes;

    for (const eventType of typesToListen) {
      eventSource.addEventListener(eventType, (event: MessageEvent) => {
        // 只记录非空的 lastEventId（后端按序发送 id: 字段）
        if (event.lastEventId) {
          lastEventIdRef.current = event.lastEventId;
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
