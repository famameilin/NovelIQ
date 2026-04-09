/**
 * 创建时间: 2026-04-07
 * 创建者: GLM-5
 * 任务: WebSocket 流式数据状态管理
 * 说明: 管理流式数据连接状态、任务进度、LLM 输出缓冲和阶段完成时间
 */
import { create } from "zustand";
import type { ProgressDetail, LLMOutputData } from "@/api/streamTypes";
import { appConfig } from "@/config";

interface StreamState {
  isConnected: boolean;
  currentTaskId: string | null;
  progress: ProgressDetail | null;
  llmOutputs: Map<string, string[]>;
  stageDurations: Map<string, number>;
  error: string | null;

  setConnected: (connected: boolean) => void;
  setTaskId: (taskId: string | null) => void;
  updateProgress: (progress: ProgressDetail) => void;
  appendLLMOutput: (data: LLMOutputData) => void;
  setStageDuration: (stage: string, duration: number) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const initialState = {
  isConnected: false,
  currentTaskId: null,
  progress: null,
  llmOutputs: new Map<string, string[]>(),
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
        llmOutputs: new Map<string, string[]>(),
        stageDurations: new Map<string, number>(),
        error: null,
      };
    }),

  updateProgress: (progress) => set({ progress }),

  appendLLMOutput: (data) =>
    set((state) => {
      const key = `${data.phase}-${data.chunk_id ?? 0}`;
      const newOutputs = new Map(state.llmOutputs);
      const existing = newOutputs.get(key) ?? [];
      newOutputs.set(key, [...existing, data.content]);

      // LRU 淘汰：超出上限时删除最早插入的 key
      if (newOutputs.size > appConfig.maxLLMOutputKeys) {
        const oldestKey = newOutputs.keys().next().value;
        if (oldestKey !== undefined) newOutputs.delete(oldestKey);
      }

      return { llmOutputs: newOutputs };
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
