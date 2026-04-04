/**
 * 创建时间: 2026-04-04
 * 创建者: GLM-5
 * 任务: Phase1-G 收尾
 * 说明: 小说状态管理 store，管理当前小说ID、任务ID和小说列表缓存
 *
 * 修改时间: 2026-04-04
 * 修改者: GLM-5
 * 修改内容:
 * - 新增 novelsCache 字段用于缓存小说列表
 * - 新增 setNovelsCache 方法用于设置缓存
 * - 新增 getNovelById 方法用于根据 ID 获取小说
 * - 修改 clear 方法，清空缓存
 */
import { create } from "zustand";
import type { Novel } from "@/api/types";

interface NovelState {
  currentNovelId: string | null;
  currentTaskId: string | null;

  // 小说列表缓存（供 TopBar 面包屑等跨页面复用）
  novelsCache: Novel[];

  setNovel: (novelId: string) => void;
  setTask: (taskId: string) => void;
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
