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
  }, []);

  useEffect(() => {
    if (!url) return;

    const eventSource = new EventSource(url);
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
      "task_complete",
      "task_error",
      "task_cancelled",
      "message",
    ];

    const typesToListen = eventTypes || defaultEventTypes;

    for (const eventType of typesToListen) {
      eventSource.addEventListener(eventType, (event: MessageEvent) => {
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
