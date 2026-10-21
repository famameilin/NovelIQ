/** 任务状态与按真实模型流分组的有界输出 */
import { create } from "zustand";
import { emptyAnalysisProjection, mergeAnalysisNotice, type AnalysisProjection, type AnalysisNotice, type ExecutionRecord } from "./analysisProjection";
import { appConfig } from "@/config";
import type { TaskStatus } from "@/api/types";
import type { StreamEventData, ToolCallStatus } from "@/api/streamTypes";
export interface ToolCallEntry { name: string; status: ToolCallStatus; detail: string; }
export interface StreamBlock { kind: "thinking" | "output"; tools: ToolCallEntry[]; text: string; }
export interface LLMStreamGroup {
  groupKey: string; agentType: string; chapterId: number; streamId: string; invocationId?: string | null;
  outputText: string; thinkingText: string; outputTotalChars: number; thinkingTotalChars: number;
  toolTotalChars: number; blocks: StreamBlock[]; lastUpdatedAt: number;
}
const _MAX_BLOCKS_PER_GROUP = 100;
interface StreamState {
  projection: AnalysisProjection; snapshotReady: boolean; notificationWarning: string | null;
  selectedInvocation: string | null; pinnedExecution: ExecutionRecord | null;
  applyNotice: (taskId: string, type: string, data: unknown, seq?: number) => void;
  selectExecution: (id: string | null) => void;
  isConnected: boolean; currentTaskId: string | null; status: TaskStatus | null;
  llmOutputs: Map<string, LLMStreamGroup>; activeStreamSelections: Map<string, string>;
  error: string | null; resumeEpoch: number;
  setConnected: (value: boolean) => void; setTaskId: (value: string | null) => void;
  resetStreamForTask: (value: string | null) => void;
  setStatus: (value: TaskStatus) => void; appendLLMOutput: (data: StreamEventData) => void;
  setActiveStreamSelection: (scope: string, groupKey: string) => void;
  setError: (value: string | null) => void; reset: () => void;
}
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
    const toolStatus: ToolCallStatus =
      status === "success" || status === "failed" ? status : "started";
    const detail = message || "";
    // llm_output 延迟 120ms 批量刷入，success/failed 到达时 started 条目可能落在更早的 thinking 块；
    // 因此从末尾向前扫描全部 thinking 块原地更新，避免同一工具显示两行
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
const empty = () => ({projection: emptyAnalysisProjection(), snapshotReady: false, notificationWarning: null as string | null,
  selectedInvocation: null as string | null, pinnedExecution: null as ExecutionRecord | null, isConnected: false, currentTaskId: null, status: null,
  llmOutputs: new Map<string, LLMStreamGroup>(), activeStreamSelections: new Map<string, string>(), error: null});
export const useStreamStore = create<StreamState>((set) => ({
  ...empty(), resumeEpoch: 0,
  selectExecution: (id) => set((state) => ({selectedInvocation: id, pinnedExecution: id ? state.projection.executions[id] ?? null : null})),
  applyNotice: (taskId, type, raw, seq) => set((state) => {
    if (state.currentTaskId !== taskId) return {};
    if (!raw || typeof raw !== "object") return {};
    const data = raw as AnalysisNotice;
    if (data.task_id && data.task_id !== taskId) return {};
    if (type === "notification_status") {
      const sync = raw as {warning: string | null; sync_pending: boolean};
      return {notificationWarning: sync.warning, projection: {...state.projection, sync_pending: sync.sync_pending}};
    }
    const projection = type === "snapshot" ? raw as AnalysisProjection
      : mergeAnalysisNotice(state.projection, type, data, seq ?? state.projection.cursor);
    return {projection, snapshotReady: state.snapshotReady || type === "snapshot",
      pinnedExecution: (state.selectedInvocation && projection.executions[state.selectedInvocation]) || state.pinnedExecution,
      error: projection.error};
  }),
  setConnected: (isConnected) => set({isConnected}),
  setStatus: (status) => set({status}),
  setTaskId: (currentTaskId) => set((state) => state.currentTaskId === currentTaskId ? {} : {...empty(), currentTaskId}),
  resetStreamForTask: (currentTaskId) => set((state) => ({
    ...(state.currentTaskId === currentTaskId ? {} : empty()),
    currentTaskId, snapshotReady: false, resumeEpoch: state.resumeEpoch + 1,
  })),
  setError: (error) => set({error}), reset: () => set(empty()),
  setActiveStreamSelection: (scope, groupKey) => set((state) => {
    const activeStreamSelections = new Map(state.activeStreamSelections);
    activeStreamSelections.set(scope, groupKey); return {activeStreamSelections};
  }),
  appendLLMOutput: (data) => set((state) => {
    if (!data.stream_id || !data.invocation_id) throw new Error("模型通信缺少真实 Agent 或流身份");
    const groupKey = `${data.invocation_id}:${data.stream_id}`;
    const outputs = new Map(state.llmOutputs);
    const group = outputs.get(groupKey) ?? {groupKey, agentType: data.agent_type ?? "",
      chapterId: data.chapter_id ?? 0, streamId: data.stream_id, invocationId: data.invocation_id,
      outputText: "", thinkingText: "", outputTotalChars: 0, thinkingTotalChars: 0, toolTotalChars: 0,
      blocks: [], lastUpdatedAt: 0};
    outputs.set(groupKey, {..._appendBoundedLLMOutput(group, data.action, data.content, data.status, data.message), lastUpdatedAt: Date.now()});
    while (outputs.size > appConfig.maxLLMOutputKeys) outputs.delete(outputs.keys().next().value!);
    return {llmOutputs: outputs};
  }),
}));
