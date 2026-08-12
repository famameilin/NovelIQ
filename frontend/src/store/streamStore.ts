/** 管理任务进度与多流 LLM 输出状态 */
import { create } from "zustand";
import type { StreamEventData, ToolCallStatus } from "@/api/streamTypes";
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
  chunkId: number;
  streamId: string | null;
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

  setConnected: (connected: boolean) => void;
  setTaskId: (taskId: string | null) => void;
  updateProgress: (progress: StreamEventData) => void;
  appendLLMOutput: (data: StreamEventData) => void;
  setActiveStreamSelection: (scopeKey: string, groupKey: string) => void;
  setStageDuration: (stage: string, duration: number) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

/** 按 chunk/phase 维度生成活跃流作用域键 */
export function buildLLMOutputScopeKey(data: {
  stage: string;
  chunk_id: number;
  sub_stage: string;
}): string {
  return `${data.stage}-${data.chunk_id}-${data.sub_stage || "default"}`;
}

/** 生成多流分组键，并兼容缺失 stream_id 的旧事件 */
export function buildLLMOutputGroupKey(data: {
  stage: string;
  chunk_id: number;
  sub_stage: string;
  stream_id?: string | null;
}): string {
  return `${buildLLMOutputScopeKey(data)}-${data.stream_id || "default"}`;
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
      chunk_id: group.chunkId,
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
    chunk_id: deletedGroup.chunkId,
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
        error: null,
      };
    }),

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
        },
      };
    }),

  appendLLMOutput: (data) =>
    set((state) => {
      const scopeKey = buildLLMOutputScopeKey({
        stage: data.stage,
        chunk_id: data.chunk_id ?? 0,
        sub_stage: data.sub_stage,
      });
      const groupKey = buildLLMOutputGroupKey({
        stage: data.stage,
        chunk_id: data.chunk_id ?? 0,
        sub_stage: data.sub_stage,
        stream_id: data.stream_id,
      });
      const now = Date.now();
      const newOutputs = new Map(state.llmOutputs);
      const existing = newOutputs.get(groupKey);
      const nextGroup: LLMStreamGroup = {
        groupKey,
        stage: data.stage,
        subStage: data.sub_stage,
        chunkId: data.chunk_id ?? 0,
        streamId: data.stream_id ?? null,
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

      // LRU 淘汰：超出上限时删除最早插入的 key
      while (newOutputs.size > appConfig.maxLLMOutputKeys) {
        const oldestEntry = newOutputs.entries().next().value as [string, LLMStreamGroup] | undefined;
        if (!oldestEntry) {
          break;
        }
        const [oldestKey, deletedGroup] = oldestEntry;
        newOutputs.delete(oldestKey);
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
