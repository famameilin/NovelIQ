import { useCallback, useEffect, useMemo, useState } from "react";
import type { NavigateFunction } from "react-router-dom";

import type { GraphChange } from "@/api/types";

import { buildGraphUrl, buildTimelineSelectionUrl } from "./graphPageNavigation";

interface UseGraphDeepLinkSelectionOptions {
  novelId?: string;
  taskScopeId: string | null;
  timelineUrl: string | null;
  urlChangeId: string | null;
  urlSelectedChunk: string | null;
  loadedChanges: GraphChange[];
  sortedChanges: GraphChange[];
  navigate: NavigateFunction;
}

/**
 *   - chunk-only deep-link 只在当前变化窗口里唯一命中时才允许自动选中
 *   - 带稳定 change_id 的 deep-link 一旦 miss，不再偷偷回退到同 chunk 其他变化
 */
function getUniqueChunkChange(changes: GraphChange[], chunkId: number | null): GraphChange | null {
  if (chunkId == null) {
    return null;
  }
  const chunkChanges = changes.filter((change) => change.effective_chunk_id === chunkId);
  return chunkChanges.length === 1 ? chunkChanges[0] ?? null : null;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把 deep-link 解析、回退提示和 URL 同步独立出来，避免分页与跳转状态交叉耦合
export function useGraphDeepLinkSelection({
  novelId,
  taskScopeId,
  timelineUrl,
  urlChangeId,
  urlSelectedChunk,
  loadedChanges,
  sortedChanges,
  navigate,
}: UseGraphDeepLinkSelectionOptions) {
  const [selectedChangeId, setSelectedChangeId] = useState<string | null>(null);
  const [hasUserSelectedChange, setHasUserSelectedChange] = useState(false);

  const initialChangeId = useMemo(() => urlChangeId?.trim() || null, [urlChangeId]);

  const initialSelectedChunk = useMemo(() => {
    if (!urlSelectedChunk) {
      return null;
    }
    const parsed = Number(urlSelectedChunk);
    return Number.isInteger(parsed) ? parsed : null;
  }, [urlSelectedChunk]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional reset on deep-link params change
    setHasUserSelectedChange(false);
    setSelectedChangeId(null);
  }, [initialChangeId, initialSelectedChunk, taskScopeId]);

  useEffect(() => {
    if (hasUserSelectedChange) return;
    if (initialChangeId == null && initialSelectedChunk == null) return;

    const matchedChange =
      initialChangeId != null
        ? loadedChanges.find((change) => change.change_id === initialChangeId) ?? null
        : null;
    if (matchedChange) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional sync from loaded changes
      setSelectedChangeId(matchedChange.change_id);
      return;
    }

    if (initialChangeId != null) {
      setSelectedChangeId(null);
      return;
    }

    const fallbackChange = getUniqueChunkChange(loadedChanges, initialSelectedChunk);
    if (fallbackChange) {
      setSelectedChangeId(fallbackChange.change_id);
      return;
    }

    setSelectedChangeId(null);
  }, [hasUserSelectedChange, initialChangeId, initialSelectedChunk, loadedChanges]);

  const selectedChange = useMemo(() => {
    if (sortedChanges.length === 0) return null;
    if (selectedChangeId == null) {
      return initialChangeId != null || initialSelectedChunk != null ? null : sortedChanges[0];
    }
    return sortedChanges.find((change) => change.change_id === selectedChangeId) ?? null;
  }, [initialChangeId, initialSelectedChunk, selectedChangeId, sortedChanges]);

  const activeSelectedChangeId = selectedChange?.change_id ?? null;

  const deepLinkResolvedChangeId = useMemo(() => {
    if (initialChangeId != null) {
      const matchedChange = sortedChanges.find((change) => change.change_id === initialChangeId);
      if (matchedChange) {
        return matchedChange.change_id;
      }
      return null;
    }
    if (initialSelectedChunk != null) {
      return getUniqueChunkChange(sortedChanges, initialSelectedChunk)?.change_id ?? null;
    }
    return null;
  }, [initialChangeId, initialSelectedChunk, sortedChanges]);

  const graphSelectionHint = useMemo(() => {
    if (hasUserSelectedChange) {
      return null;
    }
    if (
      activeSelectedChangeId != null &&
      (deepLinkResolvedChangeId == null || activeSelectedChangeId !== deepLinkResolvedChangeId)
    ) {
      return null;
    }
    if (initialChangeId == null && initialSelectedChunk == null) {
      return null;
    }
    if (initialChangeId != null) {
      const matchedChange = sortedChanges.find((change) => change.change_id === initialChangeId);
      if (matchedChange) {
        return null;
      }
      // 2026-08-12: change_id 可能落在当前分页窗口之外（后页），
      // 提示用户可继续加载更多；加载更多合并进新变化后，上方 effect 会自动补选中
      return "未在当前图谱变化窗口定位到指定变化，可能在后页，点击加载更多可继续查找。";
    }
    if (initialSelectedChunk != null) {
      const chunkMatchedChanges = sortedChanges.filter((change) => change.effective_chunk_id === initialSelectedChunk);
      if (chunkMatchedChanges.length === 0) {
        return "未在当前变化窗口定位到指定时间节点的图谱变化。";
      }
      if (chunkMatchedChanges.length > 1) {
        return "该时间块包含多条图谱变化，请手动选择具体变化。";
      }
    }
    return null;
  }, [
    activeSelectedChangeId,
    deepLinkResolvedChangeId,
    hasUserSelectedChange,
    initialChangeId,
    initialSelectedChunk,
    sortedChanges,
  ]);

  const handleSelectChange = useCallback(
    (change: GraphChange) => {
      setHasUserSelectedChange(true);
      setSelectedChangeId(change.change_id);
      if (!novelId || !taskScopeId) {
        return;
      }
      navigate(
        buildGraphUrl(novelId, taskScopeId, {
          chunkId: change.effective_chunk_id,
          changeId: change.change_id,
        }),
        { replace: true }
      );
    },
    [navigate, novelId, taskScopeId]
  );

  const handleGoTimeline = useCallback(() => {
    if (!timelineUrl) {
      return;
    }
    navigate(
      buildTimelineSelectionUrl(timelineUrl, {
        selectedNodeId: selectedChange?.change_id ?? null,
        chunkId: selectedChange?.effective_chunk_id ?? initialSelectedChunk,
        changeId: selectedChange?.change_id,
      })
    );
  }, [initialSelectedChunk, navigate, selectedChange, timelineUrl]);

  const handleOpenTimelineChunk = useCallback(
    (chunkId?: number, changeId?: string | null, selectedNodeId?: string | null) => {
      if (!timelineUrl || chunkId == null) return;
      navigate(
        buildTimelineSelectionUrl(timelineUrl, {
          selectedNodeId,
          chunkId,
          changeId,
        })
      );
    },
    [navigate, timelineUrl]
  );

  return {
    activeSelectedChangeId,
    graphSelectionHint,
    handleGoTimeline,
    handleOpenTimelineChunk,
    handleSelectChange,
    initialChangeId,
    initialSelectedChunk,
    selectedChange,
  };
}
