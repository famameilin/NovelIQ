import { useCallback, useState } from "react";

/** 调用方必须包含完整任务身份与页面名，只共享存储动作，不共享页面状态 */
export function useNarrativeState<T extends object>(key: string, initial: T) {
  function read(): T {
    try {
      const persisted = JSON.parse(localStorage.getItem(key) ?? "{}");
      // 只恢复当前页面声明的字段，其余功能状态不随交互写回
      return Object.fromEntries(Object.entries(initial).map(([field, fallback]) => [field, Object.hasOwn(persisted, field) ? persisted[field] : fallback])) as T;
    }
    catch { return initial; }
  }
  const [stored, setStored] = useState(() => ({ key, value: read() }));
  // 证据切章会改变键，先切换本章位置，避免把上一章的位置写入新章
  let state = stored.value;
  if (stored.key !== key) {
    state = read();
    setStored({ key, value: state });
  }
  const update = useCallback((patch: Partial<T> | ((previous: T) => Partial<T>)) => {
    setStored(storedValue => {
      const previous = storedValue.value;
      const next = { ...previous, ...(typeof patch === "function" ? patch(previous) : patch) };
      try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* 存储被禁用时保留本次交互 */ }
      return { key, value: next };
    });
  }, [key]);
  return [state, update] as const;
}
