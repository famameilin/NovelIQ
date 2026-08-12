import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getGraphChanges } from "@/api/results";
import type { GraphChange, GraphChangesPageInfo } from "@/api/types";

// 2026-08-07 用于按稳定 change_id 合并章节图变化分页结果
function mergeGraphChanges(existingChanges: GraphChange[], incomingChanges: GraphChange[]): GraphChange[] {
  const merged = new Map<string, GraphChange>();
  existingChanges.forEach((change) => {
    merged.set(change.change_id, change);
  });
  incomingChanges.forEach((change) => {
    merged.set(change.change_id, change);
  });
  return Array.from(merged.values());
}

interface UseGraphChangePaginationOptions {
  novelId?: string;
  taskScopeId: string | null;
}

// 2026-08-07 用于独立加载章节图变化，避免快照接口承担历史变化分页
export function useGraphChangePagination({ novelId, taskScopeId }: UseGraphChangePaginationOptions) {
  const [loadedChanges, setLoadedChanges] = useState<GraphChange[]>([]);
  const [changesPageInfo, setChangesPageInfo] = useState<GraphChangesPageInfo | null>(null);
  const [isChangesLoading, setIsChangesLoading] = useState(false);
  const [changesLoadError, setChangesLoadError] = useState<string | null>(null);
  const changesRequestVersionRef = useRef(0);
  const currentTaskScopeIdRef = useRef<string | null>(null);
  // 2026-08-12: 快速双击"加载更多"时第二次调用可能仍处于同一渲染闭包（读到旧的
  // isChangesLoading=false）；用 in-flight 游标引用兜底，同游标重复请求直接丢弃
  const inFlightLoadMoreCursorRef = useRef<string | null>(null);

  useEffect(() => {
    currentTaskScopeIdRef.current = taskScopeId;
  }, [taskScopeId]);

  useEffect(() => {
    const requestVersion = changesRequestVersionRef.current + 1;
    changesRequestVersionRef.current = requestVersion;
    inFlightLoadMoreCursorRef.current = null;
    setLoadedChanges([]);
    setChangesPageInfo(null);
    setChangesLoadError(null);

    if (!novelId || !taskScopeId) {
      setIsChangesLoading(false);
      return;
    }

    const requestTaskId = taskScopeId;
    setIsChangesLoading(true);
    void getGraphChanges(novelId, taskScopeId)
      .then((page) => {
        if (changesRequestVersionRef.current !== requestVersion || currentTaskScopeIdRef.current !== requestTaskId) {
          return;
        }
        setLoadedChanges(page.changes);
        setChangesPageInfo(page.page_info);
      })
      .catch((error: unknown) => {
        if (changesRequestVersionRef.current !== requestVersion || currentTaskScopeIdRef.current !== requestTaskId) {
          return;
        }
        const message = error instanceof Error ? error.message : "加载图谱变化失败";
        setChangesLoadError(message);
      })
      .finally(() => {
        if (changesRequestVersionRef.current === requestVersion && currentTaskScopeIdRef.current === requestTaskId) {
          setIsChangesLoading(false);
        }
      });
  }, [novelId, taskScopeId]);

  const sortedChanges = useMemo(() => {
    return [...loadedChanges].sort((left, right) => {
      const chunkDiff = right.effective_chunk_id - left.effective_chunk_id;
      if (chunkDiff !== 0) {
        return chunkDiff;
      }
      return right.change_id.localeCompare(left.change_id, "zh-CN");
    });
  }, [loadedChanges]);

  const totalChangeCount = changesPageInfo?.total ?? sortedChanges.length;
  const hasMoreChanges = changesPageInfo?.has_more ?? false;
  const loadedChangeCount = sortedChanges.length;

  const handleLoadMoreChanges = useCallback(async () => {
    if (!novelId || !taskScopeId || !changesPageInfo?.next_cursor || isChangesLoading) {
      return;
    }
    // 同一游标的请求已在途时直接丢弃，避免快速双击产生重复请求
    if (inFlightLoadMoreCursorRef.current !== null) {
      return;
    }

    const requestTaskId = taskScopeId;
    const requestCursor = changesPageInfo.next_cursor;
    const requestVersion = changesRequestVersionRef.current + 1;
    changesRequestVersionRef.current = requestVersion;
    inFlightLoadMoreCursorRef.current = requestCursor;

    setIsChangesLoading(true);
    setChangesLoadError(null);
    try {
      const page = await getGraphChanges(novelId, taskScopeId, {
        changesCursor: requestCursor,
        changesLimit: changesPageInfo.limit,
      });
      if (changesRequestVersionRef.current !== requestVersion || currentTaskScopeIdRef.current !== requestTaskId) {
        return;
      }
      setLoadedChanges((currentChanges) => mergeGraphChanges(currentChanges, page.changes));
      setChangesPageInfo(page.page_info);
    } catch (error) {
      if (changesRequestVersionRef.current !== requestVersion || currentTaskScopeIdRef.current !== requestTaskId) {
        return;
      }
      const message = error instanceof Error ? error.message : "加载更多图谱变化失败";
      setChangesLoadError(message);
    } finally {
      inFlightLoadMoreCursorRef.current = null;
      if (changesRequestVersionRef.current === requestVersion && currentTaskScopeIdRef.current === requestTaskId) {
        setIsChangesLoading(false);
      }
    }
  }, [changesPageInfo, isChangesLoading, novelId, taskScopeId]);

  return {
    changesLoadError,
    changesPageInfo,
    handleLoadMoreChanges,
    hasMoreChanges,
    isChangesLoading,
    loadedChangeCount,
    loadedChanges,
    sortedChanges,
    totalChangeCount,
  };
}
