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
