/**
 * 创建时间: 2026-04-07
 * 创建者: GLM-5
 * 任务: WebSocket 流式数据状态管理
 * 说明: 管理流式数据连接状态、任务进度、LLM 输出缓冲和阶段完成时间
 *
 * 修改时间: 2026-04-27
 * 修改者: Codex
 * 任务: phase3-multi-stream-ui
 * 修改内容:
 * - LLM 输出从按 stage/chunk 混合拼接改成按 stream group 分流存储
 * - 新增当前 scope 的活跃流选择状态，支持“默认跟随最新流，用户切换后保持选择”
 * - 保持旧 SSE 事件在缺失 stream_id 时仍自动落入 default 单流分组
 */
import { create } from "zustand";
import type { StreamEventData } from "@/api/streamTypes";
import { appConfig } from "@/config";

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
  lastUpdatedAt: number;
}

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

/**
 * 创建时间: 2026-04-27
 * 修改者: Codex
 * 任务: phase3-multi-stream-ui
 * 新建原因: 前端需要按 chunk/phase 维度管理当前活跃流，避免不同并行 batch 的输出继续混到同一缓冲区。
 */
export function buildLLMOutputScopeKey(data: {
  stage: string;
  chunk_id: number;
  sub_stage: string;
}): string {
  return `${data.stage}-${data.chunk_id}-${data.sub_stage || "default"}`;
}

/**
 * 创建时间: 2026-04-27
 * 修改者: Codex
 * 任务: phase3-multi-stream-ui
 * 新建原因: 多流分组需要稳定 group key；旧事件缺失 stream_id 时统一收口到 default，保持单流兼容。
 */
export function buildLLMOutputGroupKey(data: {
  stage: string;
  chunk_id: number;
  sub_stage: string;
  stream_id?: string | null;
}): string {
  return `${buildLLMOutputScopeKey(data)}-${data.stream_id || "default"}`;
}

/**
 * 修改时间: 2026-04-28
 * 修改者: Codex
 * 任务: 修复后台恢复后分析页卡死与白屏
 * 修改内容:
 * - 单条流输出改为有界字符串缓冲，不再让 store 无限保留细碎 token 片段。
 * - 统一按字符数与行数双上限裁剪，避免后台恢复后 Markdown 渲染窗口持续膨胀。
 */
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

/**
 * 修改时间: 2026-04-28
 * 修改者: Codex
 * 任务: 修复后台恢复后分析页卡死与白屏
 * 修改内容:
 * - 按 action 选择 output/thinking 文本缓冲，并在写入时立即做有界裁剪。
 * - 同时累计总字符数，供 UI 摘要展示真实输出体量。
 */
function _appendBoundedLLMOutput(
  group: LLMStreamGroup,
  action: StreamEventData["action"],
  content: string,
): LLMStreamGroup {
  if (!content) {
    return group;
  }

  if (action === "thinking") {
    return {
      ...group,
      thinkingText: _trimLLMOutputText(group.thinkingText + content),
      thinkingTotalChars: group.thinkingTotalChars + content.length,
    };
  }

  return {
    ...group,
    outputText: _trimLLMOutputText(group.outputText + content),
    outputTotalChars: group.outputTotalChars + content.length,
  };
}

/**
 * 创建时间: 2026-04-27
 * 修改者: Codex
 * 任务: phase3-multi-stream-ui
 * 新建原因: 当某个分组因 LRU 被淘汰或首次进入 scope 时，需要稳定回退到该 scope 最近更新的流。
 */
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

/**
 * 创建时间: 2026-04-27
 * 修改者: Codex
 * 任务: phase3-multi-stream-ui
 * 新建原因: LRU 淘汰分组后，若当前活跃流正好被删除，需要把选择安全回退到该 scope 仍存在的最新流。
 */
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
        lastUpdatedAt: now,
      };
      newOutputs.set(groupKey, _appendBoundedLLMOutput(nextGroup, data.action, data.content));

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
