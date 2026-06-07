import { useCallback, useEffect, useMemo, useState } from "react";
import type { NavigateFunction } from "react-router-dom";

import type { GraphEvent } from "@/api/types";

import { buildGraphUrl, buildTimelineSelectionUrl } from "./graphPageNavigation";

interface UseGraphDeepLinkSelectionOptions {
  novelId?: string;
  taskScopeId: string | null;
  timelineUrl: string | null;
  urlRelationEventId: string | null;
  urlSelectedChunk: string | null;
  loadedEvents: GraphEvent[];
  sortedEvents: GraphEvent[];
  navigate: NavigateFunction;
}

/**
 *   - chunk-only deep-link 只在当前事件窗口里唯一命中时才允许自动选中
 *   - 带稳定 relation_event_id 的 deep-link 一旦 miss，不再偷偷回退到同 chunk 其他事件
 */
function getUniqueChunkEvent(events: GraphEvent[], chunkId: number | null): GraphEvent | null {
  if (chunkId == null) {
    return null;
  }
  const chunkEvents = events.filter((event) => event.chunk_id === chunkId);
  return chunkEvents.length === 1 ? chunkEvents[0] ?? null : null;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把 deep-link 解析、回退提示和 URL 同步独立出来，避免分页与跳转状态交叉耦合
export function useGraphDeepLinkSelection({
  novelId,
  taskScopeId,
  timelineUrl,
  urlRelationEventId,
  urlSelectedChunk,
  loadedEvents,
  sortedEvents,
  navigate,
}: UseGraphDeepLinkSelectionOptions) {
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [hasUserSelectedEvent, setHasUserSelectedEvent] = useState(false);

  const initialRelationEventId = useMemo(() => {
    if (!urlRelationEventId) {
      return null;
    }
    const parsed = Number(urlRelationEventId);
    return Number.isInteger(parsed) ? parsed : null;
  }, [urlRelationEventId]);

  const initialSelectedChunk = useMemo(() => {
    if (!urlSelectedChunk) {
      return null;
    }
    const parsed = Number(urlSelectedChunk);
    return Number.isInteger(parsed) ? parsed : null;
  }, [urlSelectedChunk]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional reset on deep-link params change
    setHasUserSelectedEvent(false);
    setSelectedEventId(null);
  }, [initialRelationEventId, initialSelectedChunk, taskScopeId]);

  useEffect(() => {
    if (hasUserSelectedEvent) return;
    if (initialRelationEventId == null && initialSelectedChunk == null) return;

    const matchedEvent =
      initialRelationEventId != null
        ? loadedEvents.find((event) => event.relation_event_id === initialRelationEventId) ?? null
        : null;
    if (matchedEvent) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional sync from loaded events
      setSelectedEventId(matchedEvent.relation_event_id);
      return;
    }

    if (initialRelationEventId != null) {
      setSelectedEventId(null);
      return;
    }

    const fallbackEvent = getUniqueChunkEvent(loadedEvents, initialSelectedChunk);
    if (fallbackEvent) {
      setSelectedEventId(fallbackEvent.relation_event_id);
      return;
    }

    setSelectedEventId(null);
  }, [hasUserSelectedEvent, initialRelationEventId, initialSelectedChunk, loadedEvents]);

  const selectedEvent = useMemo(() => {
    if (sortedEvents.length === 0) return null;
    if (selectedEventId == null) {
      return initialRelationEventId != null || initialSelectedChunk != null ? null : sortedEvents[0];
    }
    return sortedEvents.find((event) => event.relation_event_id === selectedEventId) ?? null;
  }, [initialRelationEventId, initialSelectedChunk, selectedEventId, sortedEvents]);

  const activeSelectedEventId = selectedEvent?.relation_event_id ?? null;

  const deepLinkResolvedEventId = useMemo(() => {
    if (initialRelationEventId != null) {
      const matchedEvent = sortedEvents.find((event) => event.relation_event_id === initialRelationEventId);
      if (matchedEvent) {
        return matchedEvent.relation_event_id;
      }
      return null;
    }
    if (initialSelectedChunk != null) {
      return getUniqueChunkEvent(sortedEvents, initialSelectedChunk)?.relation_event_id ?? null;
    }
    return null;
  }, [initialRelationEventId, initialSelectedChunk, sortedEvents]);

  const graphSelectionHint = useMemo(() => {
    if (hasUserSelectedEvent) {
      return null;
    }
    if (activeSelectedEventId != null && (deepLinkResolvedEventId == null || activeSelectedEventId !== deepLinkResolvedEventId)) {
      return null;
    }
    if (initialRelationEventId == null && initialSelectedChunk == null) {
      return null;
    }
    if (initialRelationEventId != null) {
      const matchedEvent = sortedEvents.find((event) => event.relation_event_id === initialRelationEventId);
      if (matchedEvent) {
        return null;
      }
      return "未在当前图谱事件窗口定位到指定关系事件。";
    }
    if (initialSelectedChunk != null) {
      const chunkMatchedEvents = sortedEvents.filter((event) => event.chunk_id === initialSelectedChunk);
      if (chunkMatchedEvents.length === 0) {
        return "未在当前事件窗口定位到指定时间节点的关系变化。";
      }
      if (chunkMatchedEvents.length > 1) {
        return "该时间块包含多条关系变化，请手动选择具体事件。";
      }
    }
    return null;
  }, [activeSelectedEventId, deepLinkResolvedEventId, hasUserSelectedEvent, initialRelationEventId, initialSelectedChunk, sortedEvents]);

  const handleSelectEvent = useCallback(
    (event: GraphEvent) => {
      setHasUserSelectedEvent(true);
      setSelectedEventId(event.relation_event_id);
      if (!novelId || !taskScopeId) {
        return;
      }
      navigate(
        buildGraphUrl(novelId, taskScopeId, {
          chunkId: event.chunk_id,
          relationEventId: event.relation_event_id,
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
        selectedNodeId: selectedEvent ? `relation:${selectedEvent.relation_event_id}` : null,
        chunkId: selectedEvent?.chunk_id ?? initialSelectedChunk,
        relationEventId: selectedEvent?.relation_event_id,
      })
    );
  }, [initialSelectedChunk, navigate, selectedEvent, timelineUrl]);

  const handleOpenTimelineChunk = useCallback(
    (chunkId?: number, relationEventId?: number | null, selectedNodeId?: string | null) => {
      if (!timelineUrl || chunkId == null) return;
      navigate(
        buildTimelineSelectionUrl(timelineUrl, {
          selectedNodeId,
          chunkId,
          relationEventId,
        })
      );
    },
    [navigate, timelineUrl]
  );

  return {
    activeSelectedEventId,
    graphSelectionHint,
    handleGoTimeline,
    handleOpenTimelineChunk,
    handleSelectEvent,
    initialRelationEventId,
    initialSelectedChunk,
    selectedEvent,
  };
}
