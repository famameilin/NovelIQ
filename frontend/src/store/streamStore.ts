/** 管理任务进度与多流 LLM 输出状态 */
import { create } from "zustand";
import type { StreamEventData, ToolCallStatus } from "@/api/streamTypes";
import { buildStreamExecutionScope } from "@/api/streamTypes";
import { appConfig } from "@/config";

/** 工具调用条目：工具名 + 状态 + 描述 */
export interface ToolCallEntry {
  name: string;
  status: ToolCallStatus;
  detail: string;
}

/**
 * 顺序区块：按事件到达顺序组织 LLM 展示
 * - thinking 块 = "模型思考中"，内容为工具调用列表
 * - output 块 = "模型输出"，内容为模型文本
 */
export interface StreamBlock {
  kind: "thinking" | "output";
  tools: ToolCallEntry[];
  text: string;
}

export interface LLMStreamGroup {
  groupKey: string;
  stage: string;
  subStage: string;
  chapterId: number;
  streamId: string;
  workId?: string | null;
  invocationId?: string | null;
  outputText: string;
  thinkingText: string;
  outputTotalChars: number;
  thinkingTotalChars: number;
  toolTotalChars: number;
  blocks: StreamBlock[];
  lastUpdatedAt: number;
}

/** 单个 group 内允许保留的最大区块数，超出时丢弃最旧区块 */
const _MAX_BLOCKS_PER_GROUP = 100;

interface StreamState {
  isConnected: boolean;
  currentTaskId: string | null;
  progress: StreamEventData | null;
  llmOutputs: Map<string, LLMStreamGroup>;
  activeStreamSelections: Map<string, string>;
  streamSelectionModes: Map<string, "auto" | "manual">;
  stageDurations: Map<string, number>;
  error: string | null;
  /** 2026-08-14 D5：resume 轮次信号，每次 resetStreamForTask 自增，消费方据此重置内部缓冲 */
  resumeEpoch: number;
  currentInvocations: Map<string, string>;
  retiredInvocations: Map<string, Set<string>>;
  executionChapters: Map<string, number>;

  setConnected: (connected: boolean) => void;
  setTaskId: (taskId: string | null) => void;
  /** 2026-08-14 D5：无条件重置数据并设置任务（resume 同 task_id 开新轮时使用） */
  resetStreamForTask: (taskId: string | null) => void;
  updateProgress: (progress: StreamEventData) => void;
  resetWorkOutput: (data: StreamEventData) => void;
  resetChapterOutput: (data: StreamEventData) => void;
  appendLLMOutput: (data: StreamEventData) => void;
  setActiveStreamSelection: (scopeKey: string, groupKey: string) => void;
  setStageDuration: (stage: string, duration: number) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

/** 按 chapter/phase 维度生成活跃流作用域键 */
export function buildLLMOutputScopeKey(data: {
  stage: string;
  chapter_id: number;
  sub_stage: string;
}): string {
  return `${data.stage}-${data.chapter_id}-${data.sub_stage || "default"}`;
}

/** 生成多流分组键，LLM 事件必须携带 stream_id */
export function buildLLMOutputGroupKey(data: {
  stage: string;
  chapter_id: number;
  sub_stage: string;
  stream_id: string;
  invocation_id?: string | null;
}): string {
  if (!data.stream_id) {
    throw new Error("LLM 流事件缺少 stream_id");
  }
  return `${buildLLMOutputScopeKey(data)}-${data.stream_id}${data.invocation_id ? `-${data.invocation_id}` : ""}`;
}

/** 将单条流输出裁剪到固定字符数和行数上限内 */
function _trimLLMOutputText(text: string): string {
  let trimmed = text;
  if (trimmed.length > appConfig.maxLLMOutputCharsPerGroup) {
    trimmed = trimmed.slice(-appConfig.maxLLMOutputCharsPerGroup);
  }

  const lines = trimmed.split("\n");
  if (lines.length > appConfig.maxLLMOutputLinesPerGroup) {
    trimmed = lines.slice(-appConfig.maxLLMOutputLinesPerGroup).join("\n");
  }

  return trimmed;
}

/** 追加输出文本并维护有界缓冲与累计字符数 */
function _appendBoundedLLMOutput(
  group: LLMStreamGroup,
  action: StreamEventData["action"],
  content: string,
  status?: ToolCallStatus | null,
  message?: string,
): LLMStreamGroup {
  if (!content && action !== "tool_call") {
    return group;
  }

  const blocks = group.blocks;
  const lastBlock = blocks.length > 0 ? blocks[blocks.length - 1] : null;

  if (action === "thinking") {
    // 思考信号：新一轮思考开始（内容不展示，仅作区块分隔信号）
    const nextBlocks =
      lastBlock?.kind === "thinking" ? blocks : [...blocks, { kind: "thinking" as const, tools: [], text: "" }];
    return {
      ...group,
      blocks: _trimBlocks(nextBlocks),
      thinkingText: _trimLLMOutputText(group.thinkingText + content),
      thinkingTotalChars: group.thinkingTotalChars + content.length,
    };
  }

  if (action === "tool_call") {
    const name = content || "unknown";
    // 后端可能下发空串（老版本 emit 丢 status），统一按 started 处理
    const toolStatus: ToolCallStatus =
      status === "success" || status === "failed" ? status : "started";
    const detail = message || "";
    // 2026-08-12: llm_output 延迟 120ms 批量刷入，started 之后 success/failed 到达时
    // 末尾块可能已被 output 块占据，started 条目落在更早的 thinking 块；
    // 因此从末尾向前扫描全部 thinking 块寻找 started 条目并原地更新，
    // 避免旧 started 行永久滞留"进行中"、同一工具显示两行。
    if (toolStatus !== "started") {
      let foundBlockIndex = -1;
      let foundToolIndex = -1;
      for (let index = blocks.length - 1; index >= 0; index -= 1) {
        const block = blocks[index];
        if (block.kind !== "thinking") {
          continue;
        }
        const toolIndex = block.tools.findIndex(
          (tool) => tool.name === name && tool.status === "started",
        );
        if (toolIndex >= 0) {
          foundBlockIndex = index;
          foundToolIndex = toolIndex;
          break;
        }
      }
      if (foundBlockIndex >= 0) {
        // 命中历史 started 条目：原地更新该 thinking 块的 tools，块顺序保持不变
        const nextBlocks = blocks.map((block, index) =>
          index === foundBlockIndex
            ? {
                ...block,
                tools: block.tools.map((tool, index2) =>
                  index2 === foundToolIndex ? { name, status: toolStatus, detail } : tool,
                ),
              }
            : block,
        );
        return {
          ...group,
          blocks: _trimBlocks(nextBlocks),
          toolTotalChars: group.toolTotalChars + name.length,
          thinkingTotalChars: group.thinkingTotalChars + detail.length,
        };
      }
    }
    // 未命中历史 started 条目（新工具或纯 started 信号）：维持原追加逻辑
    // 若无思考块则先建一个（工具调用属于思考过程）
    const baseBlocks =
      lastBlock?.kind === "thinking"
        ? blocks
        : [...blocks, { kind: "thinking" as const, tools: [], text: "" }];
    const thinkingBlock = baseBlocks[baseBlocks.length - 1];
    // 同一工具的 started 状态条目原地更新为 success/failed，保持一行
    const existingIndex = thinkingBlock.tools.findIndex(
      (tool) => tool.name === name && tool.status === "started",
    );
    let tools: ToolCallEntry[];
    if (existingIndex >= 0) {
      tools = thinkingBlock.tools.map((tool, index) =>
        index === existingIndex ? { name, status: toolStatus, detail } : tool,
      );
    } else {
      tools = [...thinkingBlock.tools, { name, status: toolStatus, detail }];
    }
    const nextBlocks = [...baseBlocks.slice(0, -1), { ...thinkingBlock, tools }];
    return {
      ...group,
      blocks: _trimBlocks(nextBlocks),
      toolTotalChars: group.toolTotalChars + name.length,
      thinkingTotalChars: group.thinkingTotalChars + detail.length,
    };
  }

  // output：连续输出合并进同一块
  const outputText = _trimLLMOutputText(group.outputText + content);
  const nextBlocks =
    lastBlock?.kind === "output"
      ? [...blocks.slice(0, -1), { ...lastBlock, text: _trimLLMOutputText(lastBlock.text + content) }]
      : [...blocks, { kind: "output" as const, tools: [], text: _trimLLMOutputText(content) }];
  return {
    ...group,
    blocks: _trimBlocks(nextBlocks),
    outputText,
    outputTotalChars: group.outputTotalChars + content.length,
  };
}

/** 裁剪区块数量上限，丢弃最旧区块 */
function _trimBlocks(blocks: StreamBlock[]): StreamBlock[] {
  if (blocks.length <= _MAX_BLOCKS_PER_GROUP) {
    return blocks;
  }
  return blocks.slice(-_MAX_BLOCKS_PER_GROUP);
}

/** 找到某个 scope 下最近更新的流 */
function _findLatestGroupKeyForScope(
  outputs: Map<string, LLMStreamGroup>,
  scopeKey: string,
): string | null {
  let latestGroupKey: string | null = null;
  let latestUpdatedAt = -1;
  outputs.forEach((group) => {
    const groupScopeKey = buildLLMOutputScopeKey({
      stage: group.stage,
      chapter_id: group.chapterId,
      sub_stage: group.subStage,
    });
    if (groupScopeKey !== scopeKey) {
      return;
    }
    if (group.lastUpdatedAt >= latestUpdatedAt) {
      latestUpdatedAt = group.lastUpdatedAt;
      latestGroupKey = group.groupKey;
    }
  });
  return latestGroupKey;
}

/** 分组被淘汰后，修复当前作用域的活跃流选择 */
function _repairActiveSelectionAfterDeletion(
  activeSelections: Map<string, string>,
  selectionModes: Map<string, "auto" | "manual">,
  outputs: Map<string, LLMStreamGroup>,
  deletedGroup: LLMStreamGroup,
): {
  activeSelections: Map<string, string>;
  selectionModes: Map<string, "auto" | "manual">;
} {
  const nextSelections = new Map(activeSelections);
  const nextSelectionModes = new Map(selectionModes);
  const scopeKey = buildLLMOutputScopeKey({
    stage: deletedGroup.stage,
    chapter_id: deletedGroup.chapterId,
    sub_stage: deletedGroup.subStage,
  });
  if (nextSelections.get(scopeKey) !== deletedGroup.groupKey) {
    return {
      activeSelections: nextSelections,
      selectionModes: nextSelectionModes,
    };
  }

  const fallbackGroupKey = _findLatestGroupKeyForScope(outputs, scopeKey);
  if (fallbackGroupKey) {
    nextSelections.set(scopeKey, fallbackGroupKey);
    nextSelectionModes.set(scopeKey, "auto");
  } else {
    nextSelections.delete(scopeKey);
    nextSelectionModes.delete(scopeKey);
  }
  return {
    activeSelections: nextSelections,
    selectionModes: nextSelectionModes,
  };
}

const initialState = {
  isConnected: false,
  currentTaskId: null,
  progress: null,
  llmOutputs: new Map<string, LLMStreamGroup>(),
  activeStreamSelections: new Map<string, string>(),
  streamSelectionModes: new Map<string, "auto" | "manual">(),
  stageDurations: new Map<string, number>(),
  error: null,
  resumeEpoch: 0,
  currentInvocations: new Map<string, string>(),
  retiredInvocations: new Map<string, Set<string>>(),
  executionChapters: new Map<string, number>(),
};

export const useStreamStore = create<StreamState>()((set) => ({
  ...initialState,

  setConnected: (connected) => set({ isConnected: connected }),

  setTaskId: (taskId) =>
    set((state) => {
      // 只在 taskId 真正变化时才重置数据
      if (state.currentTaskId === taskId) {
        return state;
      }
      return {
        currentTaskId: taskId,
        progress: null,
        llmOutputs: new Map<string, LLMStreamGroup>(),
        activeStreamSelections: new Map<string, string>(),
        streamSelectionModes: new Map<string, "auto" | "manual">(),
        stageDurations: new Map<string, number>(),
        currentInvocations: new Map<string, string>(),
        retiredInvocations: new Map<string, Set<string>>(),
        executionChapters: new Map<string, number>(),
        error: null,
      };
    }),

  // 同任务恢复保留有效 work 展示，真正重跑的 work 由实际 work_reset 精确替换
  resetStreamForTask: (taskId) =>
    set((state) => ({
      currentTaskId: taskId,
      progress: null,
      llmOutputs: state.currentTaskId === taskId ? state.llmOutputs : new Map<string, LLMStreamGroup>(),
      activeStreamSelections: state.currentTaskId === taskId ? state.activeStreamSelections : new Map<string, string>(),
      streamSelectionModes: state.currentTaskId === taskId ? state.streamSelectionModes : new Map<string, "auto" | "manual">(),
      currentInvocations: state.currentTaskId === taskId ? state.currentInvocations : new Map<string, string>(),
      retiredInvocations: state.currentTaskId === taskId ? state.retiredInvocations : new Map<string, Set<string>>(),
      executionChapters: state.currentTaskId === taskId ? state.executionChapters : new Map<string, number>(),
      stageDurations: new Map<string, number>(),
      error: null,
      resumeEpoch: state.resumeEpoch + 1,
    })),

  updateProgress: (progress) =>
    set((state) => {
      if (!state.progress) return { progress };
      return {
        progress: {
          ...state.progress,
          ...progress,
          // None 表示"未传"，保留旧值
          current: progress.current ?? state.progress.current,
          total: progress.total ?? state.progress.total,
          percent: progress.percent ?? state.progress.percent,
          sub_percent: progress.sub_percent ?? state.progress.sub_percent,
          // 2026-08-15 M5：HTTP 回填不携带真实章节，spread 会把 chapter_id 置为
          // undefined/null 并覆写 annotate 期间的真实章 scope，导致 LLM 输出面板
          // 按章匹配全部落空；此处与 current/total 同口径保留旧值
          chapter_id: progress.chapter_id ?? state.progress.chapter_id,
        },
      };
    }),

  resetWorkOutput: (data) => set((state) => {
    if (!data.invocation_id) return state;
    const executionScope = buildStreamExecutionScope(data);
    if (data.invocation_id && state.retiredInvocations.get(executionScope)?.has(data.invocation_id)) return state;
    if (state.currentInvocations.get(executionScope) === data.invocation_id) return state;
    const currentInvocations = new Map(state.currentInvocations);
    const executionChapters = new Map(state.executionChapters);
    const retiredInvocations = new Map(state.retiredInvocations);
    if (data.invocation_id) {
      const previous = currentInvocations.get(executionScope);
      if (previous && previous !== data.invocation_id) {
        retiredInvocations.set(executionScope, new Set([...(retiredInvocations.get(executionScope) ?? []), previous]));
      }
      currentInvocations.set(executionScope, data.invocation_id);
      executionChapters.set(executionScope, data.chapter_id ?? 0);
    }
    const scope = buildLLMOutputScopeKey({stage: data.stage, chapter_id: data.chapter_id ?? 0, sub_stage: data.sub_stage});
    const outputs = new Map(state.llmOutputs);
    for (const [key, group] of outputs) {
      if (data.work_id ? group.workId === data.work_id
        : group.stage === data.stage && group.chapterId === (data.chapter_id ?? 0) && group.subStage === data.sub_stage) {
        outputs.delete(key);
      }
    }
    const selections = new Map(state.activeStreamSelections);
    const modes = new Map(state.streamSelectionModes);
    selections.delete(scope);
    modes.delete(scope);
    return {llmOutputs: outputs, activeStreamSelections: selections, streamSelectionModes: modes,
      currentInvocations, retiredInvocations, executionChapters};
  }),
  resetChapterOutput: (data) => set((state) => {
    const currentInvocations = new Map(state.currentInvocations);
    const retiredInvocations = new Map(state.retiredInvocations);
    for (const [scope, invocation] of currentInvocations) {
      if (state.executionChapters.get(scope) === data.chapter_id) {
        retiredInvocations.set(scope, new Set([...(retiredInvocations.get(scope) ?? []), invocation]));
        currentInvocations.delete(scope);
      }
    }
    const outputs = new Map(state.llmOutputs);
    const selections = new Map(state.activeStreamSelections);
    const modes = new Map(state.streamSelectionModes);
    for (const [key, group] of outputs) {
      if (group.stage === data.stage && group.chapterId === data.chapter_id) {
        outputs.delete(key);
        const scope = buildLLMOutputScopeKey({stage: group.stage, chapter_id: group.chapterId, sub_stage: group.subStage});
        selections.delete(scope);
        modes.delete(scope);
      }
    }
    return {llmOutputs: outputs, activeStreamSelections: selections, streamSelectionModes: modes,
      currentInvocations, retiredInvocations};
  }),
  appendLLMOutput: (data) =>
    set((state) => {
      const executionScope = buildStreamExecutionScope(data);
      const current = state.currentInvocations.get(executionScope);
      if (data.work_id && !current) return state;
      if (current && current !== data.invocation_id) return state;
      const retired = state.retiredInvocations.get(executionScope);
      if (retired?.has(data.invocation_id ?? "") || retired?.size && !current) return state;
      if (!data.stream_id) {
        throw new Error("LLM 流事件缺少 stream_id");
      }
      const scopeKey = buildLLMOutputScopeKey({
        stage: data.stage,
        chapter_id: data.chapter_id ?? 0,
        sub_stage: data.sub_stage,
      });
      const groupKey = buildLLMOutputGroupKey({
        stage: data.stage,
        chapter_id: data.chapter_id ?? 0,
        sub_stage: data.sub_stage,
        stream_id: data.stream_id,
        invocation_id: data.invocation_id,
      });
      const now = Date.now();
      const newOutputs = new Map(state.llmOutputs);
      const existing = newOutputs.get(groupKey);
      const nextGroup: LLMStreamGroup = {
        groupKey,
        stage: data.stage,
        subStage: data.sub_stage,
        chapterId: data.chapter_id ?? 0,
        streamId: data.stream_id,
        workId: data.work_id,
        invocationId: data.invocation_id,
        outputText: existing?.outputText ?? "",
        thinkingText: existing?.thinkingText ?? "",
        outputTotalChars: existing?.outputTotalChars ?? 0,
        thinkingTotalChars: existing?.thinkingTotalChars ?? 0,
        toolTotalChars: existing?.toolTotalChars ?? 0,
        blocks: existing?.blocks ?? [],
        lastUpdatedAt: now,
      };
      newOutputs.set(
        groupKey,
        _appendBoundedLLMOutput(nextGroup, data.action, data.content, data.status, data.message),
      );

      const nextSelections = new Map(state.activeStreamSelections);
      const nextSelectionModes = new Map(state.streamSelectionModes);
      const previousActiveGroupKey = nextSelections.get(scopeKey);
      const selectionMode = nextSelectionModes.get(scopeKey) ?? "auto";
      if (selectionMode !== "manual" || !previousActiveGroupKey || !newOutputs.has(previousActiveGroupKey)) {
        nextSelections.set(scopeKey, groupKey);
        nextSelectionModes.set(scopeKey, "auto");
      }

      // LRU 淘汰：超出上限时按 lastUpdatedAt 找最旧条目删除（O(n) 遍历）。
      // 2026-08-13 P2-4: 原实现按插入序（Map 首项）删除实为 FIFO，正在持续写入的
      // 活跃流会因插入早而被误淘汰；按 lastUpdatedAt 淘汰则活跃流每次写入都会
      // 刷新时间戳，天然不会被误伤。
      while (newOutputs.size > appConfig.maxLLMOutputKeys) {
        let oldestKey: string | null = null;
        let oldestUpdatedAt = Infinity;
        newOutputs.forEach((group, key) => {
          if (group.lastUpdatedAt < oldestUpdatedAt) {
            oldestUpdatedAt = group.lastUpdatedAt;
            oldestKey = key;
          }
        });
        if (!oldestKey) {
          break;
        }
        const deletedGroup = newOutputs.get(oldestKey);
        newOutputs.delete(oldestKey);
        if (!deletedGroup) {
          break;
        }
        const repaired = _repairActiveSelectionAfterDeletion(
          nextSelections,
          nextSelectionModes,
          newOutputs,
          deletedGroup,
        );
        nextSelections.clear();
        repaired.activeSelections.forEach((value, key) => nextSelections.set(key, value));
        nextSelectionModes.clear();
        repaired.selectionModes.forEach((value, key) => nextSelectionModes.set(key, value));
      }

      return {
        llmOutputs: newOutputs,
        activeStreamSelections: nextSelections,
        streamSelectionModes: nextSelectionModes,
      };
    }),

  setActiveStreamSelection: (scopeKey, groupKey) =>
    set((state) => {
      const nextSelections = new Map(state.activeStreamSelections);
      const nextSelectionModes = new Map(state.streamSelectionModes);
      nextSelections.set(scopeKey, groupKey);
      nextSelectionModes.set(scopeKey, "manual");
      return {
        activeStreamSelections: nextSelections,
        streamSelectionModes: nextSelectionModes,
      };
    }),

  setStageDuration: (stage, duration) =>
    set((state) => {
      const newDurations = new Map(state.stageDurations);
      newDurations.set(stage, duration);
      return { stageDurations: newDurations };
    }),

  setError: (error) => set({ error }),

  reset: () => set(initialState),
}));
