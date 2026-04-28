import type { RefObject } from "react";

import { motion } from "framer-motion";
import { ArrowRight, History, Link2, Users } from "lucide-react";

import type { GraphData, GraphEvent, GraphNode } from "@/api/types";
import type { ForceGraphHandle, GraphNodeObject } from "@/components/charts/forceGraphTypes";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { ForceGraph } from "@/components/charts/ForceGraph";
import { GraphLegend } from "@/components/charts/GraphLegend";
import { GraphToolbar } from "@/components/charts/GraphToolbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";

interface GraphWorkspaceSectionProps {
  view?: "full" | "graph" | "events";
  graphData: GraphData;
  forceGraphRef: RefObject<ForceGraphHandle | null>;
  onNodeClick: (node: GraphNodeObject) => void;
  searchQuery: string;
  selectedRelationTypes: Set<string>;
  appearanceCountMap?: Map<string, number>;
  entityTypes: string[];
  relationTypes: string[];
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitToScreen: () => void;
  onCenter: () => void;
  onRelationTypeChange: (types: Set<string>) => void;
  onSearchChange: (query: string) => void;
  totalEventCount: number;
  loadedEventCount: number;
  hasMoreEvents: boolean;
  isEventsLoading: boolean;
  eventsLoadError: string | null;
  graphSelectionHint: string | null;
  sortedEvents: GraphEvent[];
  activeSelectedEventId: number | null;
  onSelectEvent: (event: GraphEvent) => void;
  onLoadMoreEvents: () => void;
  onGoTimeline: () => void;
  timelineUrl: string | null;
  selectedNode: GraphNode | null;
  onOpenTimelineChunk: (chunkId?: number, relationEventId?: number | null, selectedNodeId?: string | null) => void;
  selectedEvent: GraphEvent | null;
  pageSectionVariants: {
    hidden: { opacity: number; y: number };
    visible: { opacity: number; y: number };
  };
  getChangeTypeLabel: (changeType?: string | null) => string;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把图谱工作区、分页事件侧栏和联动详情区块拆到独立组件，收缩 GraphPage 的 JSX 复杂度
// 2026-04-28，任务：分析详情页单屏 Tabs 改造
// 修改原因：同一工作区需要按 tab 分别渲染图谱画布或关系变化面板，避免复制两套图谱逻辑
export function GraphWorkspaceSection({
  view = "full",
  graphData,
  forceGraphRef,
  onNodeClick,
  searchQuery,
  selectedRelationTypes,
  appearanceCountMap,
  entityTypes,
  relationTypes,
  onZoomIn,
  onZoomOut,
  onFitToScreen,
  onCenter,
  onRelationTypeChange,
  onSearchChange,
  totalEventCount,
  loadedEventCount,
  hasMoreEvents,
  isEventsLoading,
  eventsLoadError,
  graphSelectionHint,
  sortedEvents,
  activeSelectedEventId,
  onSelectEvent,
  onLoadMoreEvents,
  onGoTimeline,
  timelineUrl,
  selectedNode,
  onOpenTimelineChunk,
  selectedEvent,
  pageSectionVariants,
  getChangeTypeLabel,
}: GraphWorkspaceSectionProps) {
  return (
    <motion.section
      variants={pageSectionVariants}
      initial="hidden"
      animate="visible"
      transition={{ duration: 0.28, delay: 0.15 }}
      className={cn(
        "h-full min-h-0",
        view === "full" && "grid gap-6 xl:grid-cols-[minmax(0,1.55fr),380px]",
        view !== "full" && "block overflow-hidden"
      )}
    >
      {view !== "events" && (
      <Card id="graph-workspace" variant="elevated" className="flex h-full min-h-[420px] flex-col rounded-2xl">
        <CardHeader className="shrink-0 gap-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-1">
              <CardTitle className="text-base">关系工作区</CardTitle>
              <CardDescription>在这里可以缩放、筛选和定位人物之间的关系连接。</CardDescription>
            </div>
            <div className="pb-1">
              <GraphToolbar
                onZoomIn={onZoomIn}
                onZoomOut={onZoomOut}
                onFitToScreen={onFitToScreen}
                onCenter={onCenter}
                relationTypes={relationTypes}
                selectedRelationTypes={selectedRelationTypes}
                onRelationTypeChange={onRelationTypeChange}
                searchQuery={searchQuery}
                onSearchChange={onSearchChange}
                className="max-w-full"
              />
            </div>
          </div>
        </CardHeader>

        <CardContent className="flex min-h-0 flex-1 flex-col space-y-4">
          <div className="rounded-xl border border-border/70 bg-surface-hover/35 px-4 py-3 text-sm text-text-muted">
            可以先从上方的关系概览进入，再在这里放大、筛选并查看具体角色节点。
          </div>

          <div className="relative min-h-[320px] flex-1 overflow-hidden rounded-xl border border-border bg-surface">
            <ForceGraph
              ref={forceGraphRef}
              data={graphData}
              onNodeClick={onNodeClick}
              searchQuery={searchQuery}
              relationFilter={selectedRelationTypes}
              appearanceCountMap={appearanceCountMap}
              className="absolute inset-0"
            />

            <div className="absolute bottom-4 left-4 z-10 hidden md:block">
              <GraphLegend entityTypes={entityTypes} relationTypes={relationTypes} />
            </div>
          </div>
        </CardContent>
      </Card>
      )}

      {view !== "graph" && (
      <div className={cn("h-full space-y-4 overflow-hidden", view !== "events" && "xl:self-start")}>
        <DashboardCardShell
          title="关系变化记录"
          icon={<History className="h-4 w-4" />}
          accent="chart-4"
          headerRight={
            <Badge variant="outline">
              {loadedEventCount < totalEventCount ? `${loadedEventCount} / ${totalEventCount}` : totalEventCount}
            </Badge>
          }
          footer={
            <Button variant="outline" size="sm" onClick={onGoTimeline} disabled={!timelineUrl}>
              去时间轴联动查看
              <ArrowRight className="h-4 w-4" />
            </Button>
          }
          bodyClassName="gap-3"
        >
          <p className="text-sm text-text-muted">
            按剧情推进查看关系的建立、强化、弱化和断裂。
            {hasMoreEvents ? " 当前先展示一部分记录，可继续展开查看更多变化。" : ""}
          </p>
          <div className="space-y-3 rounded-2xl border border-border/60 bg-surface/70 p-4">
            {graphSelectionHint ? (
              <div className="rounded-xl border border-chart-negative/20 bg-chart-negative/5 p-3 text-xs leading-5 text-text-muted">
                {graphSelectionHint}
              </div>
            ) : null}
            {sortedEvents.length ? (
              <>
                <div className="space-y-3 pr-1">
                  {sortedEvents.map((event) => {
                    const isSelected = activeSelectedEventId === event.relation_event_id;
                    return (
                      <button
                        key={event.relation_event_id}
                        type="button"
                        onClick={() => onSelectEvent(event)}
                        className={cn(
                          "w-full rounded-xl border p-4 text-left transition-colors",
                          isSelected ? "border-primary/40 bg-primary/5" : "border-border bg-surface hover:bg-surface-hover"
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium text-text">
                              第 {event.chunk_id} 段 · {event.from_name} → {event.to_name}
                            </p>
                            <p className="mt-1 text-xs leading-5 text-text-muted">
                              {event.relation_type ?? "未标注关系"} · {getChangeTypeLabel(event.change_type)}
                            </p>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {(hasMoreEvents || isEventsLoading || eventsLoadError) && (
                  <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="text-xs leading-5 text-text-muted">
                        {hasMoreEvents
                          ? `已加载 ${loadedEventCount} 条，仍有 ${Math.max(totalEventCount - loadedEventCount, 0)} 条变化可继续查看。`
                          : "变化记录已全部加载。"}
                      </p>
                      <Button variant="outline" size="sm" onClick={onLoadMoreEvents} disabled={!hasMoreEvents || isEventsLoading}>
                        {isEventsLoading ? "加载中..." : "加载更多"}
                      </Button>
                    </div>
                    {eventsLoadError ? <p className="mt-2 text-xs text-chart-negative">{eventsLoadError}</p> : null}
                  </div>
                )}
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">暂无关系变化记录。</div>
            )}
          </div>
        </DashboardCardShell>

        {selectedNode?.entity_type === "character" &&
        (selectedNode.first_seen_chunk != null || selectedNode.last_seen_chunk != null) ? (
          <DashboardCardShell title="角色生命周期联动" icon={<Users className="h-4 w-4" />} accent="chart-3" bodyClassName="gap-4">
            <p className="text-sm text-text-muted">从这里可以继续查看角色在故事中的首次登场和最后活跃位置。</p>
            <div className="space-y-4 rounded-2xl border border-border/60 bg-surface/70 p-4">
              <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-4 text-sm text-text-muted">
                当前选中角色 <span className="font-medium text-text">{selectedNode.name}</span>
                {selectedNode.first_seen_chunk != null && selectedNode.last_seen_chunk != null
                  ? `，稳定生命周期覆盖第 ${selectedNode.first_seen_chunk} 段到第 ${selectedNode.last_seen_chunk} 段。`
                  : "，可继续跳到时间轴查看稳定生命周期节点。"}
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    onOpenTimelineChunk(
                      selectedNode.first_seen_chunk,
                      null,
                      selectedNode.first_seen_chunk != null
                        ? `lifecycle:entry:${selectedNode.entity_id}:${selectedNode.first_seen_chunk}`
                        : null,
                    )
                  }
                  disabled={selectedNode.first_seen_chunk == null || !timelineUrl}
                >
                  查看首次登场
                  <ArrowRight className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    onOpenTimelineChunk(
                      selectedNode.last_seen_chunk,
                      null,
                      selectedNode.last_seen_chunk != null
                        ? `lifecycle:exit:${selectedNode.entity_id}:${selectedNode.last_seen_chunk}`
                        : null,
                    )
                  }
                  disabled={selectedNode.last_seen_chunk == null || !timelineUrl}
                >
                  查看最后活跃
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </DashboardCardShell>
        ) : null}

        <DashboardCardShell title="关系变化详情" icon={<Link2 className="h-4 w-4" />} accent="chart-2" bodyClassName="gap-3">
          <p className="text-sm text-text-muted">查看当前选中关系变化的上下文说明和原文摘录。</p>
          <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
            {selectedEvent ? (
              <div className="space-y-4">
                <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-text">
                        第 {selectedEvent.chunk_id} 段 · {selectedEvent.from_name} → {selectedEvent.to_name}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-text-muted">
                        {selectedEvent.relation_type ?? "未标注关系"} · {getChangeTypeLabel(selectedEvent.change_type)}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-border bg-surface p-4">
                    <p className="text-xs uppercase tracking-wide text-text-muted">变化类型</p>
                    <p className="mt-2 text-sm font-medium text-text">{getChangeTypeLabel(selectedEvent.change_type)}</p>
                  </div>
                  <div className="rounded-xl border border-border bg-surface p-4">
                    <p className="text-xs uppercase tracking-wide text-text-muted">关系方向</p>
                    <p className="mt-2 text-sm font-medium text-text">{selectedEvent.directionality ?? "未声明"}</p>
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-surface p-4">
                  <p className="text-xs uppercase tracking-wide text-text-muted">证据摘录</p>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-text">
                    {selectedEvent.evidence?.trim() || "当前事件没有附带 evidence 文本。"}
                  </p>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-text-muted">
                选择一条关系变化后，这里会显示详细上下文。
              </div>
            )}
          </div>
        </DashboardCardShell>
      </div>
      )}
    </motion.section>
  );
}
