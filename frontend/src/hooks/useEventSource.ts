/** SSE 连接取得快照后接收增量，展示游标由状态归并入口持有 */
import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import type { SSEEventType } from "@/api/streamTypes";
export type { SSEEventType } from "@/api/streamTypes";

interface SSEEventListenerOptions {
  onEvent?: (eventType: SSEEventType, data: unknown, seq?: number) => void;
  onError?: (error: Event) => void;
  eventTypes?: SSEEventType[];
}
const defaultEventTypes: SSEEventType[] = [
  "snapshot", "stage_state", "stage_progress", "capacity", "agent_activity", "work_saved",
  "task_state", "notification_status", "llm_output", "llm_thinking", "tool_call",
  "task_complete", "task_error", "task_cancelled", "work_reset", "task_reset", "chapter_reset",
  "reconnect_required", "message",
];

export function useSSEListener(url: string | null, options: SSEEventListenerOptions = {}) {
  const {eventTypes} = options;
  const sourceRef = useRef<EventSource | null>(null);
  const [connection, setConnection] = useState<{url: string | null; connected: boolean}>({url: null, connected: false});
  const emitEvent = useEffectEvent((type: SSEEventType, data: unknown, seq?: number) => options.onEvent?.(type, data, seq));
  const emitError = useEffectEvent((error: Event) => options.onError?.(error));
  const disconnect = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    setConnection({url: null, connected: false});
  }, []);

  useEffect(() => {
    if (!url) return;
    let active = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      const source = new EventSource(url);
      sourceRef.current = source;
      const current = () => active && sourceRef.current === source;
      source.onopen = () => { if (current()) setConnection({url, connected: true}); };
      source.onerror = error => {
        if (!current()) return;
        setConnection({url, connected: false});
        emitError(error);
        if (source.readyState === 2) retry = setTimeout(connect, 1000);
      };
      for (const type of eventTypes ?? defaultEventTypes) {
        source.addEventListener(type, (event: MessageEvent) => {
          if (!current()) return;
          let data: unknown;
          try { data = JSON.parse(event.data as string); }
          catch { emitError(new Event("invalid_sse_data")); return; }
          if (type === "reconnect_required") {
            setConnection({url, connected: false});
            source.close();
            connect();
            return;
          }
          const seq = event.lastEventId ? Number(event.lastEventId) : undefined;
          if (seq !== undefined && (!Number.isSafeInteger(seq) || seq < 0)) {
            emitError(new Event("invalid_sse_cursor"));
            return;
          }
          emitEvent(type, data, seq);
        });
      }
    };
    connect();
    return () => {
      active = false;
      clearTimeout(retry);
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [url, eventTypes]);

  return {isConnected: connection.url === url && connection.connected, disconnect};
}
