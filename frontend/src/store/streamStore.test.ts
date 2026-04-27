import { beforeEach, describe, expect, it } from "vitest";

import type { StreamEventData } from "@/api/streamTypes";
import { buildLLMOutputScopeKey, useStreamStore } from "@/store/streamStore";

/**
 * 创建时间: 2026-04-27
 * 修改者: Codex
 * 任务: phase3-multi-stream-ui
 * 新建原因: 多流分组和活跃流选择逻辑迁入 store 后，需要用单元测试锁住兼容 default stream 与用户手动选择的行为。
 */
function createLLMEvent(overrides: Partial<StreamEventData>): StreamEventData {
  return {
    action: "output",
    stage: "annotate",
    sub_stage: "phase3",
    chunk_id: 3,
    stream_id: null,
    current: 3,
    total: 10,
    percent: 33,
    sub_percent: 50,
    content: "",
    message: "",
    ...overrides,
  };
}

describe("streamStore 多流分组", () => {
  beforeEach(() => {
    useStreamStore.getState().reset();
  });

  it("不同 stream_id 应落到不同 group，且 output/thinking 分开追加", () => {
    const store = useStreamStore.getState();

    store.appendLLMOutput(
      createLLMEvent({
        action: "output",
        stream_id: "phase3-3-1",
        content: "甲输出",
      }),
    );
    store.appendLLMOutput(
      createLLMEvent({
        action: "thinking",
        stream_id: "phase3-3-1",
        content: "甲思考",
      }),
    );
    store.appendLLMOutput(
      createLLMEvent({
        action: "output",
        stream_id: "phase3-3-2",
        content: "乙输出",
      }),
    );

    const groups = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(groups).toHaveLength(2);
    expect(groups[0].outputParts).toEqual(["甲输出"]);
    expect(groups[0].thinkingParts).toEqual(["甲思考"]);
    expect(groups[1].outputParts).toEqual(["乙输出"]);
    expect(groups[1].thinkingParts).toEqual([]);
  });

  it("缺失 stream_id 的旧事件应自动归入 default group", () => {
    const store = useStreamStore.getState();

    store.appendLLMOutput(
      createLLMEvent({
        action: "output",
        stream_id: null,
        content: "旧单流输出",
      }),
    );

    const groups = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(groups).toHaveLength(1);
    expect(groups[0].streamId).toBeNull();
    expect(groups[0].groupKey.endsWith("-default")).toBe(true);
  });

  it("默认选中最近更新流，用户手动切换后不应被其他流新输出抢走", () => {
    const store = useStreamStore.getState();
    const scopeKey = buildLLMOutputScopeKey({
      stage: "annotate",
      chunk_id: 3,
      sub_stage: "phase3",
    });

    store.appendLLMOutput(
      createLLMEvent({
        action: "output",
        stream_id: "phase3-3-1",
        content: "甲输出",
      }),
    );
    store.appendLLMOutput(
      createLLMEvent({
        action: "output",
        stream_id: "phase3-3-2",
        content: "乙输出",
      }),
    );

    expect(useStreamStore.getState().activeStreamSelections.get(scopeKey)).toContain("phase3-3-2");

    const firstGroupKey = Array.from(useStreamStore.getState().llmOutputs.keys())[0];
    store.setActiveStreamSelection(scopeKey, firstGroupKey);
    store.appendLLMOutput(
      createLLMEvent({
        action: "output",
        stream_id: "phase3-3-2",
        content: "乙又输出",
      }),
    );

    expect(useStreamStore.getState().activeStreamSelections.get(scopeKey)).toBe(firstGroupKey);
  });
});
