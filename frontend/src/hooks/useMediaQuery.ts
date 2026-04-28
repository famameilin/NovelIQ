/**
 * useMediaQuery - CSS 媒体查询 Hook
 *
 * 跟踪 CSS 媒体查询的匹配状态
 *
 * 修复 effect 中同步调用 setState 的警告
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
 * React hook that tracks a CSS media query match state
 */
export function useMediaQuery(query: string): boolean {
  const matches = useSyncExternalStore(
    (callback) => subscribe(query, callback),
    () => getSnapshot(query),
    getServerSnapshot
  );

  return matches;
}
