/**
 * 2026-08-12 用于验证 useSSEListener 默认注册完整事件类型集：
 * 防止 tool_call 等事件类型被遗漏导致前端静默丢弃后端事件
 */
import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetSSELastSeqForTesting, useSSEListener } from "@/hooks/useEventSource";

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
    resetSSELastSeqForTesting();
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("registers all default SSE event types including tool_call", () => {
    render(<Harness url="http://test/api/events/tasks/task-a" />);
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

  it("url 变化（taskId 切换）重建连接时不携带旧 last_seq（P1-8 跨任务串流修复）", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    // 后端按契约逐条下发 id: 字段（单调递增 seq）
    MockEventSource.fire("llm_output", {
      lastEventId: "41",
      data: JSON.stringify({ action: "output", content: "第一段" }),
    });
    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "第二段" }),
    });

    // 2026-08-13 P1-8: 切换任务重建 EventSource 时清空 last_seq，避免新任务
    // 早期事件被后端按旧任务 seq 过滤跳过（跨任务串流）；同任务断线重连
    // 由浏览器原生 Last-Event-ID 头续传
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

    MockEventSource.fire("stage_progress", {
      lastEventId: "64",
      data: JSON.stringify({ action: "progress", stage: "annotate" }),
    });

    act(() => {
      disconnectRef.current?.();
    });
    expect(MockEventSource.instances[0].closed).toBe(true);

    view.rerender(<DisconnectHarness url="http://test/api/events/tasks/task-b" />);

    expect(MockEventSource.instances[1].url).toBe("http://test/api/events/tasks/task-b");
  });

  it("同一任务下 url 重建（effect 重建）保留 last_seq，query 只回放增量（P1-1 修复）", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "41",
      data: JSON.stringify({ action: "output", content: "第一段" }),
    });
    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "第二段" }),
    });

    // 同一 task_id 下 effect 重建（StrictMode 双挂载/url 参数变化重建连接）：
    // 新建 EventSource 必须携带 last_seq，后端只回放 seq 42 之后的增量，
    // 避免 LLM 输出重复、进度回退
    view.rerender(<Harness url="http://test/api/events/tasks/task-a?view=graph" />);

    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[0].closed).toBe(true);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/api/events/tasks/task-a?view=graph&last_seq=42"
    );
  });

  it("路径段形式 task_id 同一任务重建保留 last_seq，跨任务清空（P1-1 修复）", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "带 seq" }),
    });

    view.rerender(<Harness url="http://test/api/events/tasks/task-a?verbose=1" />);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/api/events/tasks/task-a?verbose=1&last_seq=42"
    );

    view.rerender(<Harness url="http://test/api/events/tasks/task-b" />);
    expect(MockEventSource.instances[2].url).toBe("http://test/api/events/tasks/task-b");
  });

  it("监听启停（url 变 null 再恢复同一任务）保留 last_seq（P1-1 修复）", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("stage_progress", {
      lastEventId: "64",
      data: JSON.stringify({ action: "progress", stage: "annotate" }),
    });

    // 暂停监听：effect 提前返回，不重建 EventSource 也不清空 seq
    view.rerender(<Harness url={null} />);
    expect(MockEventSource.instances).toHaveLength(1);

    // 恢复同一任务：仍携带 last_seq 只回放增量
    view.rerender(<Harness url="http://test/api/events/tasks/task-a" />);
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/api/events/tasks/task-a?last_seq=64"
    );
  });

  it("组件真正卸载后重挂载同一任务仍保留 last_seq（P1-6 修复：此前 useRef 随实例销毁导致全量回放）", () => {
    const view = render(<Harness url="http://test/api/events/tasks/task-a" />);

    MockEventSource.fire("llm_output", {
      lastEventId: "42",
      data: JSON.stringify({ action: "output", content: "带 seq" }),
    });

    // 模拟路由离开：组件卸载，EventSource 关闭
    view.unmount();
    expect(MockEventSource.instances[0].closed).toBe(true);

    // 模拟返回页面：重挂载同一任务，必须携带 last_seq 只回放增量，
    // 避免 LLM 输出重复拼接、终态事件重放
    render(<Harness url="http://test/api/events/tasks/task-a" />);
    expect(MockEventSource.instances[1].url).toBe(
      "http://test/api/events/tasks/task-a?last_seq=42"
    );
  });
});
