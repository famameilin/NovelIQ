import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getGraphEvents } from "@/api/results";
import type { GraphData, GraphEvent, GraphEventsPageInfo } from "@/api/types";

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把事件窗口合并逻辑独立出来，避免 GraphPage 同时承担分页与页面渲染职责。
function mergeGraphEvents(existingEvents: GraphEvent[], incomingEvents: GraphEvent[]): GraphEvent[] {
  const merged = new Map<number, GraphEvent>();
  existingEvents.forEach((event) => {
    merged.set(event.relation_event_id, event);
  });
  incomingEvents.forEach((event) => {
    merged.set(event.relation_event_id, event);
  });
  return Array.from(merged.values());
}

interface UseGraphEventPaginationOptions {
  novelId?: string;
  taskScopeId: string | null;
  graphData?: GraphData;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 将事件分页、快照合并和 task 切换清理封装为独立 hook，收缩 GraphPage 的副作用密度。
export function useGraphEventPagination({
  novelId,
  taskScopeId,
  graphData,
}: UseGraphEventPaginationOptions) {
  const [loadedEvents, setLoadedEvents] = useState<GraphEvent[]>([]);
  const [eventsPageInfo, setEventsPageInfo] = useState<GraphEventsPageInfo | null>(null);
  const [isEventsLoading, setIsEventsLoading] = useState(false);
  const [eventsLoadError, setEventsLoadError] = useState<string | null>(null);
  const eventsRequestVersionRef = useRef(0);
  const currentTaskScopeIdRef = useRef<string | null>(null);
  const previousTaskIdRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    currentTaskScopeIdRef.current = taskScopeId;
  }, [taskScopeId]);

  useEffect(() => {
    if (!graphData) {
      return;
    }

    eventsRequestVersionRef.current += 1;
    setLoadedEvents((currentEvents) =>
      currentEvents.length > 0 ? mergeGraphEvents(currentEvents, graphData.events ?? []) : (graphData.events ?? [])
    );
    setEventsPageInfo(graphData.events_page ?? null);
    setEventsLoadError(null);
    setIsEventsLoading(false);
  }, [graphData]);

  useEffect(() => {
    const previousTaskId = previousTaskIdRef.current;
    previousTaskIdRef.current = taskScopeId;
    if (previousTaskId === undefined || previousTaskId === taskScopeId) {
      return;
    }

    // task 变化时先清掉旧分页窗口；如果新 task 已命中缓存，则立即用缓存快照回填。
    eventsRequestVersionRef.current += 1;
    setLoadedEvents(graphData?.events ?? []);
    setEventsPageInfo(graphData?.events_page ?? null);
    setEventsLoadError(null);
    setIsEventsLoading(false);
  }, [graphData, taskScopeId]);

  const sortedEvents = useMemo(() => {
    return [...loadedEvents].sort((left, right) => {
      const chunkDiff = right.chunk_id - left.chunk_id;
      if (chunkDiff !== 0) {
        return chunkDiff;
      }
      return right.relation_event_id - left.relation_event_id;
    });
  }, [loadedEvents]);

  const totalEventCount = eventsPageInfo?.total ?? sortedEvents.length;
  const hasMoreEvents = eventsPageInfo?.has_more ?? false;
  const loadedEventCount = sortedEvents.length;

  const handleLoadMoreEvents = useCallback(async () => {
    if (!novelId || !taskScopeId || !eventsPageInfo?.next_cursor || isEventsLoading) {
      return;
    }

    const requestTaskId = taskScopeId;
    const requestCursor = eventsPageInfo.next_cursor;
    const requestVersion = eventsRequestVersionRef.current + 1;
    eventsRequestVersionRef.current = requestVersion;

    setIsEventsLoading(true);
    setEventsLoadError(null);
    try {
      const page = await getGraphEvents(novelId, taskScopeId, {
        eventsCursor: requestCursor,
        eventsLimit: eventsPageInfo.limit,
      });
      if (eventsRequestVersionRef.current !== requestVersion || currentTaskScopeIdRef.current !== requestTaskId) {
        return;
      }
      setLoadedEvents((currentEvents) => mergeGraphEvents(currentEvents, page.events));
      setEventsPageInfo(page.page_info);
    } catch (error) {
      if (eventsRequestVersionRef.current !== requestVersion || currentTaskScopeIdRef.current !== requestTaskId) {
        return;
      }
      const message = error instanceof Error ? error.message : "加载更多关系变化失败";
      setEventsLoadError(message);
    } finally {
      if (eventsRequestVersionRef.current === requestVersion && currentTaskScopeIdRef.current === requestTaskId) {
        setIsEventsLoading(false);
      }
    }
  }, [eventsPageInfo, isEventsLoading, novelId, taskScopeId]);

  return {
    eventsLoadError,
    eventsPageInfo,
    handleLoadMoreEvents,
    hasMoreEvents,
    isEventsLoading,
    loadedEventCount,
    loadedEvents,
    sortedEvents,
    totalEventCount,
  };
}
