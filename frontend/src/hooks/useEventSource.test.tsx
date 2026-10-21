/**
 * 用于验证 useSSEListener 默认注册完整事件类型集：
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

  it("慢客户端重连后拒绝旧连接迟到事件", () => {
    const received = vi.fn();
    function Listener() {
      useSSEListener("http://test/api/events/tasks/task-a", {onEvent: received});
      return null;
    }
    render(<Listener />);
    const old = MockEventSource.instances[0];
    act(() => MockEventSource.fire("reconnect_required", {data: JSON.stringify({reason: "backpressure"})}));
    expect(old.closed).toBe(true);
    expect(MockEventSource.instances).toHaveLength(2);
    act(() => old.handlers.get("llm_output")?.({data: JSON.stringify({content: "迟到"}), lastEventId: "99"}));
    expect(received).not.toHaveBeenCalled();
    act(() => MockEventSource.fire("snapshot", {data: JSON.stringify({cursor: 100}), lastEventId: "100"}));
    expect(received).toHaveBeenCalledWith("snapshot", {cursor: 100}, 100);
  });

  it("无效 JSON 和游标不交付归并入口", () => {
    const received = vi.fn(), failed = vi.fn();
    function Listener() {
      useSSEListener("http://test/api/events/tasks/task-a", {onEvent: received, onError: failed});
      return null;
    }
    render(<Listener />);
    act(() => MockEventSource.fire("llm_output", {data: "{", lastEventId: "5"}));
    act(() => MockEventSource.fire("llm_output", {data: "{}", lastEventId: "invalid"}));
    expect(received).not.toHaveBeenCalled();
    expect(failed).toHaveBeenCalledTimes(2);
  });

  it("registers all default SSE event types including tool_call", () => {
    render(<Harness url="http://test/api/events/tasks/task-a" />);
    expect(MockEventSource.instances).toHaveLength(1);
    const registered = MockEventSource.instances[0].registeredTypes;

    for (const eventType of [
      "snapshot", "stage_state", "stage_progress", "capacity", "agent_activity", "work_saved", "notification_status",
      "llm_output",
      "llm_thinking",
      "tool_call",
      "task_complete",
      "task_error",
      "task_cancelled",
      "task_reset",
      "chapter_reset",
      "reconnect_required",
      "message",
    ]) {
      expect(registered).toContain(eventType);
    }
  });

  it("registers only requested event types when eventTypes is provided", () => {
    function CustomHarness() {
      useSSEListener("http://test/api/events/tasks/task-a", {
        eventTypes: ["llm_output", "tool_call"],
        onEvent: () => undefined,
      });
      return null;
    }
    render(<CustomHarness />);
    const registered = MockEventSource.instances[0].registeredTypes;
    expect(registered).toEqual(new Set(["llm_output", "tool_call"]));
  });

  it("url 变化（taskId 切换）重建连接时不携带旧 last_seq", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "41",
      data: JSON.stringify({ action: "output", content: "第一段" }),
    });
    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "第二段" }),
    });

    view.rerender(<Harness url="http://test/api/events/tasks/task-b" />);

    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[0].closed).toBe(true);
    expect(MockEventSource.instances[1].url).toBe("http://test/api/events/tasks/task-b");
  });

  it("url 已带 query 时重建不带 last_seq，且无 lastEventId 时不追加参数", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);
    expect(MockEventSource.instances[0].url).toBe("http://test/api/events/tasks/task-a");

    MockEventSource.fire("tool_call", {
      lastEventId: "7",
      data: JSON.stringify({ action: "tool_call", content: "search_pool" }),
    });

    view.rerender(<Harness url="http://test/api/events/tasks/task-b" />);

    expect(MockEventSource.instances[1].url).toBe("http://test/api/events/tasks/task-b");
  });

  it("url 变化重建清空 seq，新连接从全量回放开始", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "带 seq" }),
    });
    MockEventSource.fire("llm_output", {
      data: JSON.stringify({ action: "output", content: "无 seq" }),
    });

    view.rerender(<Harness url="http://test/api/events/tasks/task-b" />);

    expect(MockEventSource.instances[1].url).toBe("http://test/api/events/tasks/task-b");
  });

  it("disconnect 后切换任务重建连接不带旧 seq（避免跨任务去重串流）", () => {
    const disconnectRef: { current: (() => void) | null } = { current: null };
    function DisconnectHarness({ url }: { url: string }) {
      const { disconnect } = useSSEListener(url, { onEvent: () => undefined });
      useEffect(() => {
        disconnectRef.current = disconnect;
      }, [disconnect]);
      return null;
    }
    const view = render(<DisconnectHarness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "64",
      data: JSON.stringify({ action: "output", content: "模型输出" }),
    });

    act(() => {
      disconnectRef.current?.();
    });
    expect(MockEventSource.instances[0].closed).toBe(true);

    view.rerender(<DisconnectHarness url="http://test/api/events/tasks/task-b" />);

    expect(MockEventSource.instances[1].url).toBe("http://test/api/events/tasks/task-b");
  });

  it("同一任务下 url 重建（effect 重建）重新取快照", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "41",
      data: JSON.stringify({ action: "output", content: "第一段" }),
    });
    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "第二段" }),
    });

    view.rerender(<Harness url="http://test/api/events/tasks/task-a?view=graph" />);

    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[0].closed).toBe(true);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/api/events/tasks/task-a?view=graph"
    );
  });

  it("路径段形式 task_id 重建均从各自快照开始", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "带 seq" }),
    });

    view.rerender(<Harness url="http://test/api/events/tasks/task-a?verbose=1" />);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/api/events/tasks/task-a?verbose=1"
    );

    view.rerender(<Harness url="http://test/api/events/tasks/task-b" />);
    expect(MockEventSource.instances[2].url).toBe("http://test/api/events/tasks/task-b");
  });

  it("监听启停（url 变 null 再恢复同一任务）重新取快照", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "64",
      data: JSON.stringify({ action: "output", content: "模型输出" }),
    });

    view.rerender(<Harness url={null} />);
    expect(MockEventSource.instances).toHaveLength(1);

    view.rerender(<Harness url="http://test/api/events/tasks/task-a" />);
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/api/events/tasks/task-a"
    );
  });

  it("组件真正卸载后重挂载同一任务仍重新取快照", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "带 seq" }),
    });

    view.unmount();
    expect(MockEventSource.instances[0].closed).toBe(true);

    render(<Harness url="http://test/api/events/tasks/task-a" />);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/api/events/tasks/task-a"
    );
  });
});
