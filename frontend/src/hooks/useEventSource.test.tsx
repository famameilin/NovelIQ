/**
 * 2026-08-12 用于验证 useSSEListener 默认注册完整事件类型集：
 * 防止 tool_call 等事件类型被遗漏导致前端静默丢弃后端事件
 */
import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSSEListener } from "@/hooks/useEventSource";

class MockEventSource {
  static instances: MockEventSource[] = [];
  registeredTypes = new Set<string>();
  handlers = new Map<string, (event: { lastEventId?: string; data?: unknown }) => void>();
  closed = false;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, handler?: (event: { lastEventId?: string; data?: unknown }) => void) {
    this.registeredTypes.add(type);
    if (handler) {
      this.handlers.set(type, handler);
    }
  }

  close() {
    this.closed = true;
  }

  static reset() {
    MockEventSource.instances = [];
  }

  /** 触发最近一个实例的指定事件类型监听器（模拟后端 SSE 消息） */
  static fire(type: string, event: { lastEventId?: string; data?: unknown }) {
    const instance = MockEventSource.instances[MockEventSource.instances.length - 1];
    instance?.handlers.get(type)?.(event);
  }
}

function Harness({ url }: { url: string | null }) {
  useSSEListener(url, { onEvent: () => undefined });
  return null;
}

describe("useSSEListener", () => {
  beforeEach(() => {
    MockEventSource.reset();
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("registers all default SSE event types including tool_call", () => {
    render(<Harness url="http://test/stream" />);
    expect(MockEventSource.instances).toHaveLength(1);
    const registered = MockEventSource.instances[0].registeredTypes;

    for (const eventType of [
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
    ]) {
      expect(registered).toContain(eventType);
    }
  });

  it("registers only requested event types when eventTypes is provided", () => {
    function CustomHarness() {
      useSSEListener("http://test/stream", {
        eventTypes: ["llm_output", "tool_call"],
        onEvent: () => undefined,
      });
      return null;
    }
    render(<CustomHarness />);
    const registered = MockEventSource.instances[0].registeredTypes;
    expect(registered).toEqual(new Set(["llm_output", "tool_call"]));
  });

  it("重建连接（url 变化触发 effect 重跑）时 URL 携带 last_seq=上次的 lastEventId", () => {
    const view = render(<Harness url="http://test/stream?task_id=task-a" />);

    // 后端按契约逐条下发 id: 字段（单调递增 seq）
    MockEventSource.fire("llm_output", {
      lastEventId: "41",
      data: JSON.stringify({ action: "output", content: "第一段" }),
    });
    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "第二段" }),
    });

    // url 变化：effect 重建 EventSource，新连接不带 Last-Event-ID，应手动拼接 last_seq
    view.rerender(<Harness url="http://test/stream?task_id=task-b" />);

    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[0].closed).toBe(true);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/stream?task_id=task-b&last_seq=42",
    );
  });

  it("url 已带 query 时 last_seq 用 & 拼接，且无 lastEventId 时不追加参数", () => {
    const view = render(<Harness url="http://test/stream?task_id=task-a" />);
    expect(MockEventSource.instances[0].url).toBe("http://test/stream?task_id=task-a");

    MockEventSource.fire("tool_call", {
      lastEventId: "7",
      data: JSON.stringify({ action: "tool_call", content: "search_pool" }),
    });

    view.rerender(<Harness url="http://test/stream?task_id=task-b" />);

    expect(MockEventSource.instances[1].url).toBe(
      "http://test/stream?task_id=task-b&last_seq=7",
    );
  });

  it("不带 lastEventId 的事件不应覆盖已记录的 seq", () => {
    const view = render(<Harness url="http://test/stream?task_id=task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "带 seq" }),
    });
    MockEventSource.fire("llm_output", {
      data: JSON.stringify({ action: "output", content: "无 seq" }),
    });

    view.rerender(<Harness url="http://test/stream?task_id=task-b" />);

    expect(MockEventSource.instances[1].url).toBe(
      "http://test/stream?task_id=task-b&last_seq=42",
    );
  });

  it("disconnect 后重建连接仍保留上次 seq（跨重建去重）", () => {
    const disconnectRef: { current: (() => void) | null } = { current: null };
    function DisconnectHarness({ url }: { url: string }) {
      const { disconnect } = useSSEListener(url, { onEvent: () => undefined });
      useEffect(() => {
        disconnectRef.current = disconnect;
      }, [disconnect]);
      return null;
    }
    const view = render(<DisconnectHarness url="http://test/stream?task_id=task-a" />);

    MockEventSource.fire("stage_progress", {
      lastEventId: "64",
      data: JSON.stringify({ action: "progress", stage: "annotate" }),
    });

    act(() => {
      disconnectRef.current?.();
    });
    expect(MockEventSource.instances[0].closed).toBe(true);

    view.rerender(<DisconnectHarness url="http://test/stream?task_id=task-b" />);

    expect(MockEventSource.instances[1].url).toBe(
      "http://test/stream?task_id=task-b&last_seq=64",
    );
  });
});
