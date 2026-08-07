/**
 * TimelineNodeDetail - 节点详情展开组件
 *
 * 点击节点后展开的详情面板，显示事件描述、角色、关系变化等
 *
 *   - 详情面板改为消费 node_id / anchor_chunk_id 新合同
 *   - 展示 score_breakdown、graph_changes 与 lifecycle_events 新结构
 *   - 图谱回跳仅在原子节点具备稳定 change_id 时附带图谱选择参数
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

const relationChangeKindLabels: Record<string, string> = {
  assert: "建立",
  reinforce: "强化",
  weaken: "弱化",
  break: "断裂",
  refine: "修订",
  supersede: "替代",
  retract: "撤回",
};

export interface TimelineNodeDetailProps {
  node: TimelineDetailNode | null;
  atomicNodes: TimelineNodeType[];
  novelId: string;
  taskId: string;
  selectedGraphChangeId?: string | null;
  onSelectAtomicNode?: (node: TimelineNodeType) => void;
  onClose?: () => void;
  className?: string;
}

function isAtomicTimelineNode(node: TimelineDetailNode | null): node is TimelineNodeType {
  return node != null && "node_subtype" in node;
}

/**
 *   - 外部传入的 selectedGraphChangeId 只有在确实属于当前节点时才可信
 *   - 若外部值不属于当前节点，则回退到节点自身唯一图谱变化，避免生成不可能成立的 graph deep-link
 */
function resolveNodeGraphChangeId(
  node: TimelineNodeType | null,
  selectedGraphChangeId: string | null,
): string | null {
  if (!node) {
    return null;
  }

  const nodeGraphChangeIds = Array.from(new Set((node.graph_changes ?? []).map((change) => change.change_id)));

  if (selectedGraphChangeId != null && nodeGraphChangeIds.includes(selectedGraphChangeId)) {
    return selectedGraphChangeId;
  }
  return nodeGraphChangeIds.length === 1 ? nodeGraphChangeIds[0] ?? null : null;
}

export function TimelineNodeDetail({
  node,
  atomicNodes,
  novelId,
  taskId,
  selectedGraphChangeId = null,
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

  const graphChangeId = useMemo(() => {
    return resolveNodeGraphChangeId(isAtomicTimelineNode(node) ? node : null, selectedGraphChangeId);
  }, [node, selectedGraphChangeId]);

  const shouldSelectGraphChange = isAtomicTimelineNode(node) && graphChangeId != null;

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
    if (shouldSelectGraphChange) {
      params.set("selected_chunk", String(node.anchor_chunk_id));
      params.set("change_id", graphChangeId);
    }
    navigate(`/novels/${novelId}/graph?${params.toString()}`);
  }, [graphChangeId, navigate, node, novelId, shouldSelectGraphChange, taskId]);

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

            {isAtomicTimelineNode(node) && node.graph_changes && node.graph_changes.length > 0 ? (
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-chart-2">
                  <Link2 className="h-3.5 w-3.5" />
                  <span>图谱变化</span>
                </div>
                <div className="space-y-2">
                  {node.graph_changes.map((change) => (
                    <div
                      key={change.change_id}
                      className={cn(
                        "rounded-md p-3 text-xs",
                        change.change_id === selectedGraphChangeId
                          ? "border border-primary/30 bg-primary/5"
                          : "bg-surface-hover",
                      )}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        {change.change_kind === "relation" ? (
                          <>
                            <span className="font-medium">{change.from_char ?? "未知实体"}</span>
                            <ArrowRight className="h-3 w-3 text-text-muted" />
                            <span className="font-medium">{change.to_char ?? "未知实体"}</span>
                            {change.relation_type ? (
                              <Badge variant="outline" className="text-[10px]">
                                {change.relation_type}
                              </Badge>
                            ) : null}
                          </>
                        ) : (
                          <span className="font-medium">{change.entity_name ?? "未知实体"}状态更新</span>
                        )}
                        <Badge variant="secondary" className="text-[10px]">
                          {change.change_kind === "relation"
                            ? relationChangeKindLabels[change.relation_change_kind ?? ""] ?? "关系更新"
                            : "状态更新"}
                        </Badge>
                        <Badge variant="outline" className="text-[10px]">
                          变化 {change.change_id}
                        </Badge>
                        {change.directionality ? (
                          <Badge variant="outline" className="text-[10px]">
                            {change.directionality}
                          </Badge>
                        ) : null}
                      </div>
                      {change.evidence[0]?.reason ? (
                        <p className="mt-2 leading-5 text-text-muted">{change.evidence[0].reason}</p>
                      ) : null}
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
