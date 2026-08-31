import { useState, type RefObject } from "react";

import { motion } from "framer-motion";
import { ArrowRight, History, Link2, Users } from "lucide-react";

import type { GraphChange, GraphData, GraphNode } from "@/api/types";
import type { ForceGraphHandle, GraphNodeObject } from "@/components/charts/forceGraphTypes";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { ForceGraph } from "@/components/charts/ForceGraph";
import { GraphLegend } from "@/components/charts/GraphLegend";
import { GraphToolbar } from "@/components/charts/GraphToolbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { formatAnalysisLabel } from "@/lib/analysisLabels";

interface GraphWorkspaceSectionProps {
  view?: "full" | "graph" | "changes";
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
  totalChangeCount: number;
  loadedChangeCount: number;
  hasMoreChanges: boolean;
  isChangesLoading: boolean;
  changesLoadError: string | null;
  graphSelectionHint: string | null;
  sortedChanges: GraphChange[];
  activeSelectedChangeId: string | null;
  onSelectChange: (change: GraphChange) => void;
  onLoadMoreChanges: () => void;
  onGoTimeline: () => void;
  timelineUrl: string | null;
  selectedNode: GraphNode | null;
  onOpenTimelineChapter: (chapterId?: number | null, changeId?: string | null, selectedNodeId?: string | null) => void;
  selectedChange: GraphChange | null;
  pageSectionVariants: {
    hidden: { opacity: number; y: number };
    visible: { opacity: number; y: number };
  };
  getChangeTypeLabel: (changeType?: string | null) => string;
}

const INITIAL_VISIBLE_CHANGE_COUNT = 8;
const CHANGE_REVEAL_STEP = 20;

/**
 * 2026-08-31，作用：将图谱关系方向转换为中文文案
 * 简要说明：关系变化详情不再直接显示后端英文枚举
 */
function getDirectionalityLabel(directionality?: "directed" | "bidirectional" | null): string {
  if (directionality === "bidirectional") return "双向关系";
  if (directionality === "directed") return "单向关系";
  return "方向未标注";
}

/**
 * 2026-04-23，作用：承载关系画布、变化记录和联动详情
 * 简要说明：根据主视图组合画布与变化区域，并分批展示已经加载的变化记录
 */
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
  totalChangeCount,
  loadedChangeCount,
  hasMoreChanges,
  isChangesLoading,
  changesLoadError,
  graphSelectionHint,
  sortedChanges,
  activeSelectedChangeId,
  onSelectChange,
  onLoadMoreChanges,
  onGoTimeline,
  timelineUrl,
  selectedNode,
  onOpenTimelineChapter,
  selectedChange,
  pageSectionVariants,
  getChangeTypeLabel,
}: GraphWorkspaceSectionProps) {
  const [visibleChangeCount, setVisibleChangeCount] = useState(INITIAL_VISIBLE_CHANGE_COUNT);
  const selectedChangeIndex = activeSelectedChangeId
    ? sortedChanges.findIndex((change) => change.change_id === activeSelectedChangeId)
    : -1;
  const effectiveVisibleChangeCount = Math.max(visibleChangeCount, selectedChangeIndex + 1);
  const visibleChanges = sortedChanges.slice(0, effectiveVisibleChangeCount);
  const canRevealLoadedChanges = visibleChanges.length < sortedChanges.length;

  /**
   * 2026-08-31，作用：分批展开已经加载的图谱变化
   * 简要说明：先控制页面长度，再在本地记录显示完后继续请求下一页
   */
  function handleRevealMoreChanges() {
    setVisibleChangeCount((current) => current + CHANGE_REVEAL_STEP);
  }

  return (
    <motion.section
      variants={pageSectionVariants}
      initial="hidden"
      animate="visible"
      transition={{ duration: 0.28, delay: 0.15 }}
      className={cn(
        "min-h-0",
        view === "full" && "grid grid-cols-[minmax(0,1.55fr)_380px] items-start gap-6",
        view !== "full" && "block"
      )}
    >
      {view !== "changes" && (
      <Card id="graph-workspace" variant="elevated" className="flex min-h-[520px] flex-col rounded-lg">
        <CardHeader className="shrink-0 gap-4">
          <div className="space-y-1">
            <CardTitle className="text-base">当前人物关系</CardTitle>
            <CardDescription>截至第 {graphData.chapter_order} 章的有效实体与关系</CardDescription>
          </div>
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
            className="w-full"
          />
        </CardHeader>

        <CardContent className="flex min-h-0 flex-1 flex-col">
          <div className="relative min-h-[420px] flex-1 overflow-hidden rounded-lg border border-border bg-surface">
            <ForceGraph
              ref={forceGraphRef}
              data={graphData}
              onNodeClick={onNodeClick}
              searchQuery={searchQuery}
              relationFilter={selectedRelationTypes}
              appearanceCountMap={appearanceCountMap}
              className="absolute inset-0"
            />

            <div className="absolute bottom-4 left-4 z-10 block">
              <GraphLegend entityTypes={entityTypes} relationTypes={relationTypes} />
            </div>
          </div>
        </CardContent>
      </Card>
      )}

      {view !== "graph" && (
      <div
        className={cn(
          "space-y-4",
          view === "changes"
            ? "grid h-full min-h-0 grid-cols-[minmax(0,1.18fr)_minmax(340px,0.82fr)] gap-4"
            : "self-start",
        )}
      >
        <DashboardCardShell
          title="图谱变化记录"
          icon={<History className="h-4 w-4" />}
          accent="chart-4"
          className={cn(view === "changes" && "flex min-h-[420px] flex-col")}
          contentClassName={cn(view === "changes" && "flex flex-col")}
          headerRight={
            <Badge variant="outline">
              {visibleChanges.length < totalChangeCount ? `${visibleChanges.length} / ${totalChangeCount}` : totalChangeCount}
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
            按剧情推进查看实体状态和关系的稳定变化。
            {hasMoreChanges ? " 当前先展示一部分记录，可继续展开查看更多变化。" : ""}
          </p>
          <div className={cn(
            "space-y-3 rounded-2xl border border-border/60 bg-surface/70 p-4",
            view === "changes" && "flex min-h-0 flex-1 flex-col"
          )}>
            {graphSelectionHint ? (
              <div className="rounded-xl border border-chart-negative/20 bg-chart-negative/5 p-3 text-xs leading-5 text-text-muted">
                {graphSelectionHint}
              </div>
            ) : null}
            {visibleChanges.length ? (
              <>
                <div className={cn(
                  "space-y-3 pr-1"
                )}>
                  {visibleChanges.map((change) => {
                    const isSelected = activeSelectedChangeId === change.change_id;
                    return (
                      <button
                        key={change.change_id}
                        type="button"
                        onClick={() => onSelectChange(change)}
                        className={cn(
                          "w-full rounded-xl border p-4 text-left transition-colors",
                          isSelected ? "border-primary/40 bg-primary/5" : "border-border bg-surface hover:bg-surface-hover"
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium text-text">
                              第 {change.effective_chapter_id} 章 ·{" "}
                              {change.change_kind === "relation"
                                ? `${change.from_name ?? "未知实体"} → ${change.to_name ?? "未知实体"}`
                                : change.entity_name ?? "未知实体"}
                            </p>
                            <p className="mt-1 text-xs leading-5 text-text-muted">
                              {change.change_kind === "relation"
                                ? `${formatAnalysisLabel(change.relation_type, "relation")} · ${getChangeTypeLabel(change.relation_change_kind)}`
                                : `状态更新 · ${change.changes.length} 项变化`}
                            </p>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {(canRevealLoadedChanges || hasMoreChanges || isChangesLoading || changesLoadError) && (
                  <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="text-xs leading-5 text-text-muted">
                        {canRevealLoadedChanges
                          ? `当前展示 ${visibleChanges.length} 条，已加载的 ${loadedChangeCount} 条记录可继续展开。`
                          : hasMoreChanges
                            ? `已展示本批 ${loadedChangeCount} 条，仍有 ${Math.max(totalChangeCount - loadedChangeCount, 0)} 条可继续加载。`
                            : "变化记录已全部展示。"}
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={canRevealLoadedChanges ? handleRevealMoreChanges : onLoadMoreChanges}
                        disabled={(!canRevealLoadedChanges && !hasMoreChanges) || isChangesLoading}
                      >
                        {isChangesLoading ? "加载中..." : canRevealLoadedChanges ? "显示更多" : "加载更多"}
                      </Button>
                    </div>
                    {changesLoadError ? <p className="mt-2 text-xs text-chart-negative">{changesLoadError}</p> : null}
                  </div>
                )}
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">暂无关系变化记录。</div>
            )}
          </div>
        </DashboardCardShell>

          <div className={cn(view === "changes" ? "flex min-h-0 flex-col gap-4" : "space-y-4")}>
          {selectedNode?.entity_type === "character" &&
          (selectedNode.first_seen_chapter != null || selectedNode.last_seen_chapter != null) ? (
            <DashboardCardShell title="角色生命周期联动" icon={<Users className="h-4 w-4" />} accent="chart-3" bodyClassName="gap-4">
              <p className="text-sm text-text-muted">从这里可以继续查看角色在故事中的首次登场和最后活跃位置。</p>
              <div className="space-y-4 rounded-2xl border border-border/60 bg-surface/70 p-4">
                <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-4 text-sm text-text-muted">
                  当前选中角色 <span className="font-medium text-text">{selectedNode.name}</span>
                  {selectedNode.first_seen_chapter != null && selectedNode.last_seen_chapter != null
                    ? `，稳定生命周期覆盖第 ${selectedNode.first_seen_chapter} 章到第 ${selectedNode.last_seen_chapter} 章。`
                    : "，可继续跳到时间轴查看稳定生命周期节点。"}
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      onOpenTimelineChapter(
                        selectedNode.first_seen_chapter,
                        null,
                        selectedNode.first_seen_chapter != null
                          ? `lifecycle:entry:${selectedNode.entity_id}:${selectedNode.first_seen_chapter}`
                          : null,
                      )
                    }
                    disabled={selectedNode.first_seen_chapter == null || !timelineUrl}
                  >
                    查看首次登场
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      onOpenTimelineChapter(
                        selectedNode.last_seen_chapter,
                        null,
                        selectedNode.last_seen_chapter != null
                          ? `lifecycle:exit:${selectedNode.entity_id}:${selectedNode.last_seen_chapter}`
                          : null,
                      )
                    }
                    disabled={selectedNode.last_seen_chapter == null || !timelineUrl}
                  >
                    查看最后活跃
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </DashboardCardShell>
          ) : null}

          <DashboardCardShell
            title="关系变化详情"
            icon={<Link2 className="h-4 w-4" />}
            accent="chart-2"
            className={cn(view === "changes" && "flex min-h-0 flex-1 flex-col")}
            contentClassName={cn(view === "changes" && "flex flex-col")}
            bodyClassName="gap-3"
          >
            <p className="text-sm text-text-muted">当前选中变化的章节、类型与关系方向</p>
            <div className={cn(
              "rounded-2xl border border-border/60 bg-surface/70 p-4",
              view === "changes" && "min-h-0 flex-1"
            )}>
              {selectedChange ? (
                <div className="space-y-4">
                  <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                          <p className="text-sm font-medium text-text">
                           第 {selectedChange.effective_chapter_id} 章 ·{" "}
                           {selectedChange.change_kind === "relation"
                             ? `${selectedChange.from_name ?? "未知实体"} → ${selectedChange.to_name ?? "未知实体"}`
                             : selectedChange.entity_name ?? "未知实体"}
                          </p>
                          <p className="mt-1 text-xs leading-5 text-text-muted">
                           {selectedChange.change_kind === "relation"
                             ? `${formatAnalysisLabel(selectedChange.relation_type, "relation")} · ${getChangeTypeLabel(selectedChange.relation_change_kind)}`
                             : `状态更新 · ${selectedChange.changes.length} 项变化`}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-xl border border-border bg-surface p-4">
                      <p className="text-xs uppercase tracking-wide text-text-muted">变化类型</p>
                      <p className="mt-2 text-sm font-medium text-text">
                        {selectedChange.change_kind === "relation"
                          ? getChangeTypeLabel(selectedChange.relation_change_kind)
                          : "状态更新"}
                      </p>
                    </div>
                    <div className="rounded-xl border border-border bg-surface p-4">
                      <p className="text-xs uppercase tracking-wide text-text-muted">关系方向</p>
                      <p className="mt-2 text-sm font-medium text-text">
                        {selectedChange.change_kind === "relation"
                          ? getDirectionalityLabel(selectedChange.directionality)
                          : "实体状态"}
                      </p>
                    </div>
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
      </div>
      )}
    </motion.section>
  );
}
