import { create } from "zustand";

interface NovelState {
  currentNovelId: string | null;
  currentTaskId: string | null;
  setNovel: (novelId: string) => void;
  setTask: (taskId: string) => void;
  clear: () => void;
}

export const useNovelStore = create<NovelState>()((set) => ({
  currentNovelId: null,
  currentTaskId: null,
  setNovel: (novelId) => set({ currentNovelId: novelId, currentTaskId: null }),
  setTask: (taskId) => set({ currentTaskId: taskId }),
  clear: () => set({ currentNovelId: null, currentTaskId: null }),
}));
