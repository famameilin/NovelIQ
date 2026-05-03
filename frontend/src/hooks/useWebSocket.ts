/** WebSocket 连接管理 Hook，提供重连、心跳和连接状态追踪 */
import { useCallback, useEffect, useRef, useState } from "react";
import { appConfig } from "@/config";

function jitter(): number {
  return Math.random() * 1_000;
}

interface UseWebSocketOptions {
  url: string;
  enabled?: boolean;
  onMessage?: (data: unknown) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  /** 是否启用自动重连，默认 true */
  reconnect?: boolean;
  /** 最大重连次数，默认 10 */
  maxReconnectAttempts?: number;
  /** 是否启用心跳检测，默认 true */
  heartbeat?: boolean;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  send: (data: unknown) => void;
  disconnect: () => void;
  reconnect: () => void;
}

export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const {
    url,
    enabled = true,
    onMessage,
    onOpen,
    onClose,
    onError,
    reconnect: shouldReconnect = true,
    maxReconnectAttempts = appConfig.wsMaxReconnectAttempts,
    heartbeat: enableHeartbeat = true,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pongTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isManualCloseRef = useRef(false);
  const connectRef = useRef<() => void>(() => {});

  const callbacksRef = useRef({
    onMessage,
    onOpen,
    onClose,
    onError,
  });

  useEffect(() => {
    callbacksRef.current = { onMessage, onOpen, onClose, onError };
  }, [onMessage, onOpen, onClose, onError]);

  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const clearHeartbeat = useCallback(() => {
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
    if (pongTimerRef.current) {
      clearTimeout(pongTimerRef.current);
      pongTimerRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback((ws: WebSocket) => {
    if (!enableHeartbeat) return;

    clearHeartbeat();

    heartbeatTimerRef.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send("ping");

        // 如果上一次 pong 还没回来，直接判定假死
        if (pongTimerRef.current) {
          ws.close(4000, "heartbeat timeout");
          return;
        }

        pongTimerRef.current = setTimeout(() => {
          // pong 超时 → 主动断开触发 onclose → 自动重连
          ws.close(4000, "pong timeout");
        }, appConfig.wsPongTimeout);
      }
    }, appConfig.wsHeartbeatInterval);
  }, [enableHeartbeat, clearHeartbeat]);

  const stopHeartbeat = useCallback(() => {
    clearHeartbeat();
  }, [clearHeartbeat]);

  /* ---------------------------------------------------------------- */
  /*  连接生命周期                                                       */
  /* ---------------------------------------------------------------- */

  const disconnect = useCallback(() => {
    isManualCloseRef.current = true;
    clearReconnectTimeout();
    stopHeartbeat();
    reconnectAttemptsRef.current = 0;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, [clearReconnectTimeout, stopHeartbeat]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    clearReconnectTimeout();
    stopHeartbeat();
    isManualCloseRef.current = false;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      reconnectAttemptsRef.current = 0;
      startHeartbeat(ws);
      callbacksRef.current.onOpen?.();
    };

    ws.onmessage = (event: MessageEvent) => {
      if (typeof event.data === "string" && event.data === "pong") {
        if (pongTimerRef.current) {
          clearTimeout(pongTimerRef.current);
          pongTimerRef.current = null;
        }
        return;
      }

      let data: unknown;
      try {
        data = JSON.parse(event.data as string);
      } catch {
        data = event.data;
      }
      callbacksRef.current.onMessage?.(data);
    };

    ws.onclose = () => {
      stopHeartbeat();
      setIsConnected(false);
      if (!isManualCloseRef.current) {
        callbacksRef.current.onClose?.();
      }

      if (
        shouldReconnect &&
        !isManualCloseRef.current &&
        reconnectAttemptsRef.current < maxReconnectAttempts
      ) {
        const attempt = reconnectAttemptsRef.current;
        reconnectAttemptsRef.current += 1;

        // 指数退避 + 随机抖动
        const delay = Math.min(
          appConfig.wsReconnectBaseDelay * Math.pow(2, attempt) + jitter(),
          appConfig.wsReconnectMaxDelay
        );

        reconnectTimeoutRef.current = setTimeout(() => {
          connectRef.current();
        }, delay);
      }
    };

    ws.onerror = (error: Event) => {
      callbacksRef.current.onError?.(error);
    };
  }, [
    url,
    shouldReconnect,
    maxReconnectAttempts,
    clearReconnectTimeout,
    stopHeartbeat,
    startHeartbeat,
  ]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const reconnect = useCallback(() => {
    disconnect();
    connect();
  }, [disconnect, connect]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message = typeof data === "string" ? data : JSON.stringify(data);
      wsRef.current.send(message);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      const timer = setTimeout(() => disconnect(), 0);
      return () => clearTimeout(timer);
    }
    connect();

    return () => {
      disconnect();
    };
  }, [connect, disconnect, enabled]);

  return {
    isConnected,
    send,
    disconnect,
    reconnect,
  };
}
