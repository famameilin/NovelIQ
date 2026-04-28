/**
 * TimelineNodeDetail - 节点详情展开组件
 *
 * 点击节点后展开的详情面板，显示事件描述、角色、关系变化等
 *
 *   - 详情面板改为消费 node_id / anchor_chunk_id 新合同
 *   - 展示 score_breakdown、relation_events 与 lifecycle_events 新结构
 *   - 图谱回跳仅在 relation 节点具备稳定 relation_event_id 时附带图谱选择参数
 *
 *   - 支持复合节点详情与原子节点详情双模式
 *   - 复合节点只提供稳定 child atomic node 入口，不再构造模糊 graph deep-link
 */

import { useCallback, useMemo } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowRight, HelpCircle, Link2, Users, User, UserMinus, X, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import type { TimelineCompositeNode, TimelineNode as TimelineNodeType } from "@/api/types";
import { cn } from "@/lib/cn";

import { getTimelineNodePresentation } from "./timelineNodePresentation";

type TimelineDetailNode = TimelineNodeType | TimelineCompositeNode;

export interface TimelineNodeDetailProps {
  node: TimelineDetailNode | null;
  atomicNodes: TimelineNodeType[];
  novelId: string;
  taskId: string;
  selectedRelationEventId?: number | null;
  onSelectAtomicNode?: (node: TimelineNodeType) => void;
  onClose?: () => void;
  className?: string;
}

function isAtomicTimelineNode(node: TimelineDetailNode | null): node is TimelineNodeType {
  return node != null && "node_subtype" in node;
}

/**
 *   - 外部传入的 selectedRelationEventId 只有在确实属于当前节点时才可信
 *   - 若外部值不属于当前节点，则回退到节点自身唯一 relation event，避免生成不可能成立的 graph deep-link
 */
function resolveNodeGraphRelationEventId(
  node: TimelineNodeType | null,
  selectedRelationEventId: number | null,
): number | null {
  if (node?.node_type !== "relation") {
    return null;
  }

  const nodeRelationEventIds = Array.from(
    new Set(
      (node.relation_events ?? [])
        .map((relationEvent) => relationEvent.relation_event_id)
        .filter((relationEventId): relationEventId is number => relationEventId != null),
    ),
  );

  if (selectedRelationEventId != null && nodeRelationEventIds.includes(selectedRelationEventId)) {
    return selectedRelationEventId;
  }
  return nodeRelationEventIds.length === 1 ? nodeRelationEventIds[0] : null;
}

export function TimelineNodeDetail({
  node,
  atomicNodes,
  novelId,
  taskId,
  selectedRelationEventId = null,
  onSelectAtomicNode,
  onClose,
  className,
}: TimelineNodeDetailProps) {
  const navigate = useNavigate();

  const presentationSubtype =
    node == null ? "plot" : ("node_subtype" in node ? node.node_subtype : (node.node_subtypes[0] ?? "plot"));
  const presentation = node ? getTimelineNodePresentation(node.node_type, presentationSubtype) : null;
  const Icon = presentation?.icon;

  const handleCharacterClick = useCallback(
    (characterName: string) => {
      navigate(`/novels/${novelId}/characters?highlight=${encodeURIComponent(characterName)}`);
    },
    [navigate, novelId],
  );

  const graphRelationEventId = useMemo(() => {
    return resolveNodeGraphRelationEventId(isAtomicTimelineNode(node) ? node : null, selectedRelationEventId);
  }, [node, selectedRelationEventId]);

  const shouldSelectGraphEvent = isAtomicTimelineNode(node) && node.node_type === "relation" && graphRelationEventId != null;

  const childAtomicNodes = useMemo(() => {
    if (node == null || isAtomicTimelineNode(node)) {
      return [];
    }
    const atomicNodeById = new Map(atomicNodes.map((atomicNode) => [atomicNode.node_id, atomicNode]));
    return node.child_node_ids
      .map((childNodeId) => atomicNodeById.get(childNodeId) ?? null)
      .filter((childNode): childNode is TimelineNodeType => childNode != null);
  }, [atomicNodes, node]);

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
                {"start_chunk_id" in node && node.start_chunk_id !== node.end_chunk_id ? (
                  <span>范围 {node.start_chunk_id}-{node.end_chunk_id}</span>
                ) : (
                  <span>第 {node.anchor_chunk_id} 块</span>
                )}
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

            {isAtomicTimelineNode(node) && node.plot_flags ? (
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

            {isAtomicTimelineNode(node) && Object.keys(node.score_breakdown).length > 0 ? (
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

            {isAtomicTimelineNode(node) && node.lifecycle_events && node.lifecycle_events.length > 0 ? (
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

            {isAtomicTimelineNode(node) && node.relation_events && node.relation_events.length > 0 ? (
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

            {!isAtomicTimelineNode(node) ? (
              <div>
                <div className="mb-2 text-xs font-medium text-text-muted">复合节点包含的原子节点</div>
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {node.node_subtypes.map((subtype) => (
                    <Badge key={subtype} variant="outline" className="text-[10px]">
                      {subtype}
                    </Badge>
                  ))}
                </div>
                <div className="space-y-2">
                  {childAtomicNodes.length === 0 ? (
                    <p className="text-xs text-text-muted">当前复合节点暂无可展开的原子节点。</p>
                  ) : (
                    childAtomicNodes.map((childNode) => {
                      const childSubtype = childNode.node_subtype;
                      const childPresentation = getTimelineNodePresentation(childNode.node_type, childSubtype);
                      return (
                        <div key={childNode.node_id} className="rounded-md bg-surface-hover p-3 text-xs">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className="text-[10px]">
                              {childPresentation.label}
                            </Badge>
                            <span className="font-medium text-text">Chunk {childNode.anchor_chunk_id}</span>
                            <span className="text-text-muted">重要性 {childNode.importance_score.toFixed(1)}</span>
                          </div>
                          <p className="mt-2 leading-5 text-text-muted">{childNode.summary}</p>
                          <div className="mt-2 flex gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => onSelectAtomicNode?.(childNode)}
                            >
                              查看原子节点
                            </Button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            ) : null}
          </DashboardCardShell>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
