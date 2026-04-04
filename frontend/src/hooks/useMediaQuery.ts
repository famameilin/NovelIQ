/**
 * useMediaQuery - CSS 媒体查询 Hook
 * 
 * 创建时间: 2026-04-04
 * 创建者: AI Assistant
 * 任务: Sprint 1-A UI 组件
 * 说明: 跟踪 CSS 媒体查询的匹配状态
 * 
 * 修改时间: 2026-04-04
 * 修改者: AI Assistant
 * 修改内容: 修复 effect 中同步调用 setState 的警告
 */
import { useSyncExternalStore } from "react";

function getSnapshot(query: string): boolean {
  if (typeof window !== "undefined") {
    return window.matchMedia(query).matches;
  }
  return false;
}

function getServerSnapshot(): boolean {
  return false;
}

function subscribe(query: string, callback: () => void): () => void {
  const mql = window.matchMedia(query);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

/**
 * React hook that tracks a CSS media query match state.
 */
export function useMediaQuery(query: string): boolean {
  const matches = useSyncExternalStore(
    (callback) => subscribe(query, callback),
    () => getSnapshot(query),
    getServerSnapshot
  );

  return matches;
}
