import { beforeEach, describe, expect, it } from "vitest";

import type { StreamEventData } from "@/api/streamTypes";
import { buildLLMOutputScopeKey, useStreamStore } from "@/store/streamStore";

/**
 * 多流分组和活跃流选择逻辑迁入 store 后，需要用单元测试锁住兼容 default stream 与用户手动选择的行为
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
    expect(groups[0].outputText).toBe("甲输出");
    expect(groups[0].thinkingText).toBe("甲思考");
    expect(groups[0].outputTotalChars).toBe(3);
    expect(groups[0].thinkingTotalChars).toBe(3);
    expect(groups[1].outputText).toBe("乙输出");
    expect(groups[1].thinkingText).toBe("");
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

  it("单条流文本应维持有界缓冲，同时保留累计字符数", () => {
    const store = useStreamStore.getState();

    store.appendLLMOutput(
      createLLMEvent({
        action: "output",
        stream_id: "phase3-3-1",
        content: Array.from({ length: 260 }, (_, index) => `第${index + 1}行`).join("\n"),
      }),
    );

    const [group] = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(group.outputText).toContain("第260行");
    expect(group.outputText).not.toContain("第1行");
    expect(group.outputText.split("\n").length).toBeLessThanOrEqual(240);
    expect(group.outputTotalChars).toBeGreaterThan(group.outputText.length);
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
