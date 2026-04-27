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

// 2026-04-23，任务：复杂度与耦合审查 P1
// 新建原因：把 deep-link 解析、回退提示和 URL 同步独立出来，避免分页与跳转状态交叉耦合。
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
      setSelectedEventId(matchedEvent.relation_event_id);
      return;
    }

    const fallbackEvent =
      initialSelectedChunk != null ? loadedEvents.find((event) => event.chunk_id === initialSelectedChunk) ?? null : null;
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
      if (initialSelectedChunk != null) {
        const fallbackEvent = sortedEvents.find((event) => event.chunk_id === initialSelectedChunk);
        return fallbackEvent?.relation_event_id ?? null;
      }
      return null;
    }
    if (initialSelectedChunk != null) {
      const chunkMatchedEvent = sortedEvents.find((event) => event.chunk_id === initialSelectedChunk);
      return chunkMatchedEvent?.relation_event_id ?? null;
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
      if (initialSelectedChunk != null) {
        const fallbackEvent = sortedEvents.find((event) => event.chunk_id === initialSelectedChunk);
        if (fallbackEvent) {
          return "未在当前事件窗口定位到指定关系事件，已回退到同一时间节点的关系变化。";
        }
      }
      return "未在当前图谱事件窗口定位到指定关系事件。";
    }
    if (initialSelectedChunk != null) {
      const chunkMatchedEvent = sortedEvents.find((event) => event.chunk_id === initialSelectedChunk);
      if (!chunkMatchedEvent) {
        return "未在当前事件窗口定位到指定时间节点的关系变化。";
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
