/**
 * 小说作用域任务守卫 Hook（2026-08-13 P1-2）
 *
 * 提取自 GraphPage/TimelinePage 的既有守卫模式，供其余分析页统一使用：
 *
 * 1. `storeTaskId`：只有 store 的 currentNovelId 与当前路由 novelId 一致时，
 *    currentTaskId 才被视为当前小说的任务。SPA 内跨小说切换后、store 尚未同步
 *    的瞬间，旧小说的 task_id 不得被用于新小说的 SSE/查询（否则 404），
 *    也不得被回写固化成新小说 URL。
 *
 * 2. URL→store 同步：URL 上的 task_id 是 deep-link 权威，必须先同步进 store。
 *    `urlTaskSyncRef` 记录"待同步的 deep-link task_id"，URL 回写前先核对，
 *    防止旧 store 状态抢先 replace 掉合法 deep-link（GraphPage/TimelinePage
 *    同款机制）。
 */
import { useEffect, useRef } from "react";
import { useNovelStore } from "@/store/novelStore";

export interface UseNovelScopedTaskResult {
  /** 当前小说作用域内的任务 id；跨小说切换后 store 尚未同步时为 null */
  storeTaskId: string | null;
  /** 待同步的 URL deep-link task_id（防旧 store 抢先回写 URL） */
  urlTaskSyncRef: { current: string | null };
}

export function useNovelScopedTask(
  novelId: string | null | undefined,
  urlTaskId: string | null,
): UseNovelScopedTaskResult {
  const { currentNovelId, currentTaskId, setNovel, setTask } = useNovelStore();
  const urlTaskSyncRef = useRef<string | null>(
    urlTaskId && currentTaskId !== urlTaskId ? urlTaskId : null,
  );

  // URL → store 同步；用 getState() 读取最新 store 值，避免闭包捕获旧值
  // （TimelinePage 同款写法，依赖数组无需包含 currentTaskId）
  useEffect(() => {
    if (!novelId) {
      return;
    }
    setNovel(novelId);
    if (urlTaskId) {
      const currentStoreState = useNovelStore.getState();
      const currentStoreTaskId =
        currentStoreState.currentNovelId === novelId
          ? currentStoreState.currentTaskId
          : null;
      if (currentStoreTaskId !== urlTaskId) {
        urlTaskSyncRef.current = urlTaskId;
      }
      setTask(urlTaskId);
    }
  }, [novelId, setNovel, setTask, urlTaskId]);

  // 跨小说切换后，旧小说的任务不得用于当前小说
  const storeTaskId = currentNovelId === novelId ? currentTaskId : null;

  return { storeTaskId, urlTaskSyncRef };
}

/**
 * 判断是否应把 store 任务回写 URL（GraphPage/TimelinePage 的 URL 写回守卫）：
 * - store 无任务（跨小说切换/任务删除）时不写回
 * - URL 已是同一任务时不写回（顺手清掉已完成的同步标记）
 * - URL 上存在尚未同步进 store 的 deep-link 时不写回（避免旧 store 抢先覆盖）
 */
export function shouldWriteBackTaskUrl(
  urlTaskId: string | null,
  storeTaskId: string | null,
  urlTaskSyncRef: { current: string | null },
): boolean {
  if (!storeTaskId) {
    return false;
  }
  if (urlTaskId === storeTaskId) {
    if (urlTaskSyncRef.current === storeTaskId) {
      urlTaskSyncRef.current = null;
    }
    return false;
  }
  if (urlTaskId && urlTaskSyncRef.current === urlTaskId) {
    return false;
  }
  return true;
}
