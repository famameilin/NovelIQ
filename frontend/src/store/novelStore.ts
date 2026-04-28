/** 小说状态管理 store，管理当前小说、任务和小说列表缓存 */
import { create } from "zustand";
import type { Novel } from "@/api/types";

interface NovelState {
  currentNovelId: string | null;
  currentTaskId: string | null;

  // 小说列表缓存（供 TopBar 面包屑等跨页面复用）
  novelsCache: Novel[];

  setNovel: (novelId: string) => void;
  setTask: (taskId: string | null) => void;
  setNovelsCache: (novels: Novel[]) => void;
  getNovelById: (novelId: string) => Novel | undefined;
  clear: () => void;
}

export const useNovelStore = create<NovelState>()((set, get) => ({
  currentNovelId: null,
  currentTaskId: null,
  novelsCache: [],

  setNovel: (novelId) => set({ currentNovelId: novelId, currentTaskId: null }),
  setTask: (taskId) => set({ currentTaskId: taskId }),

  setNovelsCache: (novels) => set({ novelsCache: novels }),

  getNovelById: (novelId) => {
    return get().novelsCache.find((n) => n.novel_id === novelId);
  },

  clear: () => set({ currentNovelId: null, currentTaskId: null, novelsCache: [] }),
}));
