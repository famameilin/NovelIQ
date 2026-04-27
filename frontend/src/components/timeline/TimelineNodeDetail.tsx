/**
 * TimelineNodeDetail - 节点详情展开组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 点击节点后展开的详情面板，显示事件描述、角色、关系变化等
 *
 * 修改时间: 2026-04-27
 * 任务: 时间轴合同重构
 * 修改内容:
 *   - 详情面板改为消费 node_id / anchor_chunk_id 新合同
 *   - 展示 score_breakdown、relation_events 与 lifecycle_events 新结构
 *   - 图谱回跳仅在 relation 节点具备稳定 relation_event_id 时附带图谱选择参数
 */

import { useCallback, useMemo } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowRight, HelpCircle, Link2, Users, User, UserMinus, X, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import type { TimelineNode as TimelineNodeType } from "@/api/types";
import { cn } from "@/lib/cn";

import { getTimelineNodePresentation } from "./timelineNodePresentation";

export interface TimelineNodeDetailProps {
  node: TimelineNodeType | null;
  novelId: string;
  taskId: string;
  selectedRelationEventId?: number | null;
  onClose?: () => void;
  className?: string;
}

export function TimelineNodeDetail({
  node,
  novelId,
  taskId,
  selectedRelationEventId = null,
  onClose,
  className,
}: TimelineNodeDetailProps) {
  const navigate = useNavigate();

  const presentation = node ? getTimelineNodePresentation(node.node_type, node.node_subtype) : null;
  const Icon = presentation?.icon;

  const handleCharacterClick = useCallback(
    (characterName: string) => {
      navigate(`/novels/${novelId}/characters?highlight=${encodeURIComponent(characterName)}`);
    },
    [navigate, novelId],
  );

  const graphRelationEventId = useMemo(() => {
    if (selectedRelationEventId != null) {
      return selectedRelationEventId;
    }
    const uniqueRelationEventIds = Array.from(
      new Set(
        (node?.relation_events ?? [])
          .map((relationEvent) => relationEvent.relation_event_id)
          .filter((relationEventId): relationEventId is number => relationEventId != null),
      ),
    );
    return uniqueRelationEventIds.length === 1 ? uniqueRelationEventIds[0] : null;
  }, [node?.relation_events, selectedRelationEventId]);

  const shouldSelectGraphEvent = node?.node_type === "relation" && graphRelationEventId != null;

  const handleBackToGraph = useCallback(() => {
    if (!node) return;
    const params = new URLSearchParams({ task_id: taskId });
    if (shouldSelectGraphEvent) {
      params.set("selected_chunk", String(node.anchor_chunk_id));
      params.set("relation_event_id", String(graphRelationEventId));
    }
    navigate(`/novels/${novelId}/graph?${params.toString()}`);
  }, [graphRelationEventId, navigate, node, novelId, shouldSelectGraphEvent, taskId]);

  return (
    <AnimatePresence mode="wait">
      {node && presentation && Icon ? (
        <motion.div
          key="node-detail"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className={cn("overflow-hidden", className)}
        >
          <DashboardCardShell
            title={presentation.label}
            icon={<Icon className={cn("h-4 w-4", presentation.iconClassName)} />}
            accent={presentation.accent}
            showOrb
            headerRight={
              onClose ? (
                <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
                  <X className="h-4 w-4" />
                </Button>
              ) : undefined
            }
            bodyClassName="gap-4"
          >
            <div>
              <p className="text-sm text-text">{node.summary}</p>
              <div className="mt-2 flex items-center gap-4 text-xs text-text-muted">
                <span>节点 {node.node_id}</span>
                <span>第 {node.anchor_chunk_id} 块</span>
                <span>进度: {Math.round(node.progress * 100)}%</span>
                <span>重要性: {node.importance_score.toFixed(1)}</span>
              </div>
              <div className="mt-3">
                <Button variant="outline" size="sm" onClick={handleBackToGraph}>
                  回到图谱入口
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {node.characters.length > 0 ? (
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-text-muted">
                  <Users className="h-3.5 w-3.5" />
                  <span>涉及角色</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {node.characters.map((character) => (
                    <Badge
                      key={character}
                      variant="secondary"
                      className="cursor-pointer hover:bg-primary/20"
                      onClick={() => handleCharacterClick(character)}
                    >
                      {character}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}

            {node.plot_flags ? (
              <div className="flex gap-2">
                {node.plot_flags.is_pivot ? (
                  <Badge variant="outline" className="gap-1 border-chart-negative text-chart-negative">
                    <Zap className="h-3 w-3" />
                    转折点
                  </Badge>
                ) : null}
                {node.plot_flags.is_cliffhanger ? (
                  <Badge variant="outline" className="gap-1 border-chart-3 text-chart-3">
                    <HelpCircle className="h-3 w-3" />
                    悬念点
                  </Badge>
                ) : null}
                <Badge variant="outline" className="text-text-muted">
                  张力 {node.plot_flags.tension_percentile} 分位
                </Badge>
              </div>
            ) : null}

            {Object.keys(node.score_breakdown).length > 0 ? (
              <div>
                <div className="mb-2 text-xs font-medium text-text-muted">得分拆解</div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(node.score_breakdown).map(([label, score]) => (
                    <Badge key={label} variant="outline" className="text-[10px]">
                      {label}: {score.toFixed(2)}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}

            {node.lifecycle_events && node.lifecycle_events.length > 0 ? (
              <div>
                <div
                  className={cn(
                    "mb-1.5 flex items-center gap-1.5 text-xs font-medium",
                    node.node_subtype === "entry" ? "text-chart-positive" : "text-chart-negative",
                  )}
                >
                  {node.node_subtype === "entry" ? (
                    <User className="h-3.5 w-3.5" />
                  ) : (
                    <UserMinus className="h-3.5 w-3.5" />
                  )}
                  <span>{node.node_subtype === "entry" ? "角色登场" : "角色退场"}</span>
                </div>
                <p className="mb-2 text-xs leading-5 text-text-muted">
                  这里表达的是 authority lifecycle 的稳定事件，不是页面侧临时推断结果。
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {node.lifecycle_events.map((event) => (
                    <Badge
                      key={`${event.lifecycle_type}-${event.entity_id}`}
                      variant="secondary"
                      className={cn(
                        "cursor-pointer hover:bg-primary/20",
                        event.lifecycle_type === "entry"
                          ? "bg-chart-positive/10 text-chart-positive hover:bg-chart-positive/20"
                          : "bg-chart-negative/10 text-chart-negative hover:bg-chart-negative/20",
                      )}
                      onClick={() => handleCharacterClick(event.character_name)}
                    >
                      {event.character_name}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}

            {node.relation_events && node.relation_events.length > 0 ? (
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-chart-2">
                  <Link2 className="h-3.5 w-3.5" />
                  <span>关系变化</span>
                </div>
                <div className="space-y-2">
                  {node.relation_events.map((event) => (
                    <div
                      key={event.relation_event_id}
                      className={cn(
                        "rounded-md p-3 text-xs",
                        event.relation_event_id === selectedRelationEventId
                          ? "border border-primary/30 bg-primary/5"
                          : "bg-surface-hover",
                      )}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{event.from_char}</span>
                        <ArrowRight className="h-3 w-3 text-text-muted" />
                        <span className="font-medium">{event.to_char}</span>
                        <Badge variant="outline" className="text-[10px]">
                          {event.relation_type}
                        </Badge>
                        <Badge variant="secondary" className="text-[10px]">
                          {event.change_type}
                        </Badge>
                        <Badge variant="outline" className="text-[10px]">
                          事件 #{event.relation_event_id}
                        </Badge>
                        {event.directionality ? (
                          <Badge variant="outline" className="text-[10px]">
                            {event.directionality}
                          </Badge>
                        ) : null}
                        {event.confidence != null ? (
                          <Badge variant="outline" className="text-[10px]">
                            置信 {Math.round(event.confidence * 100)}%
                          </Badge>
                        ) : null}
                      </div>
                      {event.evidence ? <p className="mt-2 leading-5 text-text-muted">{event.evidence}</p> : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </DashboardCardShell>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
