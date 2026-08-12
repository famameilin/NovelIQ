/**
 * 2026-08-12 用于验证 useSSEListener 默认注册完整事件类型集：
 * 防止 tool_call 等事件类型被遗漏导致前端静默丢弃后端事件
 */
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSSEListener } from "@/hooks/useEventSource";

class MockEventSource {
  static instances: MockEventSource[] = [];
  registeredTypes = new Set<string>();
  closed = false;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string) {
    this.registeredTypes.add(type);
  }

  close() {
    this.closed = true;
  }

  static reset() {
    MockEventSource.instances = [];
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
});
