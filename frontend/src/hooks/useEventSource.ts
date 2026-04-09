/**
 * useEventSource - SSE (Server-Sent Events) 连接管理 Hook
 *
 * 创建时间: 2026-04-09
 * 创建者: TraeAI
 * 任务: 前端适配 SSE
 * 说明: 提供 SSE 连接管理，支持自动重连（浏览器原生）、事件监听
 */
import { useEffect, useRef, useCallback, useState } from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface UseEventSourceOptions {
  onMessage?: (event: MessageEvent) => void;
  onError?: (error: Event) => void;
  onOpen?: (event: Event) => void;
}

interface UseEventSourceReturn {
  isConnected: boolean;
  disconnect: () => void;
}

/* ------------------------------------------------------------------ */
/*  Hook                                                              */
/* ------------------------------------------------------------------ */

export function useEventSource(
  url: string | null,
  options: UseEventSourceOptions = {}
): UseEventSourceReturn {
  const { onMessage, onError, onOpen } = options;

  const [isConnected, setIsConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const isManualCloseRef = useRef(false);

  const disconnect = useCallback(() => {
    isManualCloseRef.current = true;
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setIsConnected(false);
  }, []);

  useEffect(() => {
    if (!url) return;

    isManualCloseRef.current = false;

    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    eventSource.onopen = (event: Event) => {
      setIsConnected(true);
      onOpen?.(event);
    };

    eventSource.onmessage = (event: MessageEvent) => {
      onMessage?.(event);
    };

    eventSource.onerror = (error: Event) => {
      setIsConnected(false);
      onError?.(error);
      if (!isManualCloseRef.current) {
        eventSource.close();
        eventSourceRef.current = null;
      }
    };

    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [url, onMessage, onError, onOpen]);

  return {
    isConnected,
    disconnect,
  };
}

/* ------------------------------------------------------------------ */
/*  SSE Event Types Helper                                            */
/* ------------------------------------------------------------------ */

export type SSEEventType =
  | "task_start"
  | "stage_start"
  | "stage_progress"
  | "stage_complete"
  | "llm_output"
  | "llm_thinking"
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
  const { onEvent, onError, eventTypes } = options;
  const eventSourceRef = useRef<EventSource | null>(null);
  const [isConnected, setIsConnected] = useState(false);

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

    eventSource.onerror = (error: Event) => {
      setIsConnected(false);
      onError?.(error);
    };

    const defaultEventTypes: SSEEventType[] = [
      "task_start",
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
        onEvent?.(eventType as SSEEventType, data);
      });
    }

    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [url, onEvent, onError, eventTypes]);

  return {
    isConnected,
    disconnect,
  };
}
