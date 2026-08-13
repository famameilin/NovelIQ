import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StreamEventData } from "@/api/streamTypes";
import { appConfig } from "@/config";
import { buildLLMOutputScopeKey, buildLLMOutputGroupKey, useStreamStore } from "@/store/streamStore";

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

describe("streamStore 顺序区块（模型思考中/模型输出）", () => {
  beforeEach(() => {
    useStreamStore.getState().reset();
  });

  it("thinking 信号新建思考块，连续 thinking 合并为一块", () => {
    const store = useStreamStore.getState();

    store.appendLLMOutput(createLLMEvent({ action: "thinking", content: "状态一" }));
    store.appendLLMOutput(createLLMEvent({ action: "thinking", content: "状态二" }));

    const [group] = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(group.blocks).toHaveLength(1);
    expect(group.blocks[0].kind).toBe("thinking");
    expect(group.blocks[0].tools).toEqual([]);
    expect(group.thinkingText).toBe("状态一状态二");
  });

  it("工具调用进入思考块：started 新建条目，success/failed 原地更新状态", () => {
    const store = useStreamStore.getState();

    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "resolve_case",
        message: "正在调用工具 resolve_case",
        status: "started",
      }),
    );
    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "write_metrics",
        message: "正在调用工具 write_metrics",
        status: "started",
      }),
    );
    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "resolve_case",
        message: "工具 resolve_case 执行成功",
        status: "success",
      }),
    );

    const [group] = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(group.blocks).toHaveLength(1);
    expect(group.blocks[0].kind).toBe("thinking");
    expect(group.blocks[0].tools).toEqual([
      { name: "resolve_case", status: "success", detail: "工具 resolve_case 执行成功" },
      { name: "write_metrics", status: "started", detail: "正在调用工具 write_metrics" },
    ]);
    expect(group.toolTotalChars).toBeGreaterThan(0);
  });

  it("输出到达新建输出块，连续输出合并；思考→输出→思考交替成块", () => {
    const store = useStreamStore.getState();

    store.appendLLMOutput(createLLMEvent({ action: "output", content: "第一段" }));
    store.appendLLMOutput(createLLMEvent({ action: "output", content: "第二段" }));
    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "search_pool",
        message: "正在调用工具 search_pool",
        status: "started",
      }),
    );
    store.appendLLMOutput(createLLMEvent({ action: "output", content: "第三段" }));

    const [group] = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(group.blocks.map((block) => block.kind)).toEqual(["output", "thinking", "output"]);
    expect(group.blocks[0].text).toBe("第一段第二段");
    expect(group.blocks[2].text).toBe("第三段");
    expect(group.outputText).toBe("第一段第二段第三段");
  });

  it("工具调用在输出之后到达时自动补建思考块", () => {
    const store = useStreamStore.getState();

    store.appendLLMOutput(createLLMEvent({ action: "output", content: "先输出" }));
    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "finish",
        message: "正在调用工具 finish",
        status: "started",
      }),
    );

    const [group] = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(group.blocks.map((block) => block.kind)).toEqual(["output", "thinking"]);
    expect(group.blocks[1].tools[0].name).toBe("finish");
  });

  it("started 之后 output 先刷入、success 后到时，应在原 thinking 块内原地更新且不产生重复行", () => {
    const store = useStreamStore.getState();

    // 真实时序：tool_call 即时刷入 store，llm_output 延迟 120ms 批量刷入，
    // 因此 started 之后 output 块先于 success 到达
    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "resolve_case",
        message: "正在调用工具 resolve_case",
        status: "started",
      }),
    );
    store.appendLLMOutput(createLLMEvent({ action: "output", content: "文本输出" }));
    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "resolve_case",
        message: "工具 resolve_case 执行成功",
        status: "success",
      }),
    );

    const [group] = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(group.blocks.map((block) => block.kind)).toEqual(["thinking", "output"]);
    expect(group.blocks[0].tools).toEqual([
      { name: "resolve_case", status: "success", detail: "工具 resolve_case 执行成功" },
    ]);
    expect(group.blocks[1].text).toBe("文本输出");
  });

  it("success 到达时末尾已是新的 thinking 块，也应回扫旧 thinking 块原地更新", () => {
    const store = useStreamStore.getState();

    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "search_pool",
        message: "正在调用工具 search_pool",
        status: "started",
      }),
    );
    store.appendLLMOutput(createLLMEvent({ action: "output", content: "文本" }));
    store.appendLLMOutput(createLLMEvent({ action: "thinking", content: "新一轮思考" }));
    store.appendLLMOutput(
      createLLMEvent({
        action: "tool_call",
        content: "search_pool",
        message: "工具 search_pool 执行成功",
        status: "success",
      }),
    );

    const [group] = Array.from(useStreamStore.getState().llmOutputs.values());
    expect(group.blocks.map((block) => block.kind)).toEqual(["thinking", "output", "thinking"]);
    expect(group.blocks[0].tools).toEqual([
      { name: "search_pool", status: "success", detail: "工具 search_pool 执行成功" },
    ]);
    expect(group.blocks[2].tools).toEqual([]);
  });
});

describe("streamStore LRU 淘汰", () => {
  beforeEach(() => {
    useStreamStore.getState().reset();
  });

  const originalMaxLLMOutputKeys = appConfig.maxLLMOutputKeys;

  function withSmallCacheSize(max: number, fn: () => void) {
    (appConfig as { maxLLMOutputKeys: number }).maxLLMOutputKeys = max;
    try {
      fn();
    } finally {
      (appConfig as { maxLLMOutputKeys: number }).maxLLMOutputKeys = originalMaxLLMOutputKeys;
    }
  }

  it("淘汰按 lastUpdatedAt 找最旧条目删除，而非插入序首个（活跃流不被淘汰，P2-4 修复）", () => {
    vi.useFakeTimers();
    try {
      withSmallCacheSize(3, () => {
        vi.setSystemTime(1000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ stream_id: "stream-a", content: "A" }),
        );
        vi.setSystemTime(2000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ stream_id: "stream-b", content: "B" }),
        );
        vi.setSystemTime(3000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ stream_id: "stream-c", content: "C" }),
        );

        // 活跃流 A 再次写入：lastUpdatedAt 最新，但插入序最旧
        vi.setSystemTime(10000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ stream_id: "stream-a", content: "A2" }),
        );

        // 新 scope 的流触发淘汰：应淘汰 lastUpdatedAt 最旧的 stream-b（t=2000），
        // FIFO 实现会错误淘汰插入序首个的 stream-a（正是当前活跃流）
        vi.setSystemTime(11000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ sub_stage: "phase1", chunk_id: 5, stream_id: "stream-d", content: "D" }),
        );

        const keys = Array.from(useStreamStore.getState().llmOutputs.keys());
        expect(keys).not.toContain(buildLLMOutputGroupKey({
          stage: "annotate", chunk_id: 3, sub_stage: "phase3", stream_id: "stream-b",
        }));
        expect(keys).toContain(buildLLMOutputGroupKey({
          stage: "annotate", chunk_id: 3, sub_stage: "phase3", stream_id: "stream-a",
        }));
        expect(keys).toContain(buildLLMOutputGroupKey({
          stage: "annotate", chunk_id: 3, sub_stage: "phase3", stream_id: "stream-c",
        }));

        // 活跃流 A 仍是 scope 的当前选中流
        const scopeKey = buildLLMOutputScopeKey({ stage: "annotate", chunk_id: 3, sub_stage: "phase3" });
        expect(useStreamStore.getState().activeStreamSelections.get(scopeKey)).toBe(
          buildLLMOutputGroupKey({ stage: "annotate", chunk_id: 3, sub_stage: "phase3", stream_id: "stream-a" }),
        );
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("被淘汰的流正是当前选中流时，选择回退到 scope 内最近更新的流（repair 逻辑保留）", () => {
    vi.useFakeTimers();
    try {
      withSmallCacheSize(3, () => {
        vi.setSystemTime(1000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ stream_id: "stream-a", content: "A" }),
        );
        vi.setSystemTime(2000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ stream_id: "stream-b", content: "B" }),
        );
        vi.setSystemTime(3000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ stream_id: "stream-c", content: "C" }),
        );

        const scopeKey = buildLLMOutputScopeKey({ stage: "annotate", chunk_id: 3, sub_stage: "phase3" });
        const groupAKey = buildLLMOutputGroupKey({
          stage: "annotate", chunk_id: 3, sub_stage: "phase3", stream_id: "stream-a",
        });
        const groupCKey = buildLLMOutputGroupKey({
          stage: "annotate", chunk_id: 3, sub_stage: "phase3", stream_id: "stream-c",
        });
        // 用户手动选中 stream-a（最旧），随后新流触发淘汰
        useStreamStore.getState().setActiveStreamSelection(scopeKey, groupAKey);
        vi.setSystemTime(4000);
        useStreamStore.getState().appendLLMOutput(
          createLLMEvent({ sub_stage: "phase1", chunk_id: 5, stream_id: "stream-d", content: "D" }),
        );

        const keys = Array.from(useStreamStore.getState().llmOutputs.keys());
        expect(keys).not.toContain(groupAKey);
        // 选中流被淘汰后回退到 scope 内 lastUpdatedAt 最新的 stream-c，模式回到 auto
        expect(useStreamStore.getState().activeStreamSelections.get(scopeKey)).toBe(groupCKey);
        expect(useStreamStore.getState().streamSelectionModes.get(scopeKey)).toBe("auto");
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
