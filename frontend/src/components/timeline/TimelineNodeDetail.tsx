/**
 * TimelineNodeDetail - 节点详情展开组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 点击节点后展开的详情面板，显示事件描述、角色、关系变化等
 */

import { useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  X,
  Zap,
  HelpCircle,
  User,
  UserMinus,
  Link2,
  Users,
  ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TimelineNode as TimelineNodeType } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const NODE_TYPE_CONFIG: Record<
  string,
  { icon: typeof Zap; colorClass: string; label: string }
> = {
  plot: { icon: Zap, colorClass: "text-primary", label: "情节节点" },
  character_entry: {
    icon: User,
    colorClass: "text-chart-positive",
    label: "角色登场",
  },
  character_exit: {
    icon: UserMinus,
    colorClass: "text-chart-negative",
    label: "角色退场",
  },
  relation_change: {
    icon: Link2,
    colorClass: "text-chart-2",
    label: "关系变化",
  },
};

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TimelineNodeDetailProps {
  node: TimelineNodeType | null;
  novelId: string;
  taskId: string;
  selectedRelationEventId?: number | null;
  onClose?: () => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function TimelineNodeDetail({
  node,
  novelId,
  taskId,
  selectedRelationEventId = null,
  onClose,
  className,
}: TimelineNodeDetailProps) {
  const navigate = useNavigate();

  const config = node ? (NODE_TYPE_CONFIG[node.node_type] || NODE_TYPE_CONFIG.plot) : null;
  const Icon = config?.icon;

  const handleCharacterClick = useCallback((characterName: string) => {
    navigate(`/novels/${novelId}/characters?highlight=${encodeURIComponent(characterName)}`);
  }, [navigate, novelId]);

  const graphRelationEventId = useMemo(() => {
    if (selectedRelationEventId != null) {
      return selectedRelationEventId;
    }

    const uniqueRelationEventIds = Array.from(
      new Set(
        (node?.relation_changes ?? [])
          .map((relationChange) => relationChange.relation_event_id)
          .filter((relationEventId): relationEventId is number => relationEventId != null)
      )
    );

    // 中文注释：时间轴页内手动点开 relation node 时，URL 里不一定已有
    // relation_event_id。若当前节点只承载一个稳定事件，就直接把它带回图谱，
    // 避免回退成 chunk 级命中而误高亮同 chunk 的其他关系变化。
    return uniqueRelationEventIds.length === 1 ? uniqueRelationEventIds[0] : null;
  }, [node?.relation_changes, selectedRelationEventId]);

  const handleBackToGraph = useCallback(() => {
    if (!node) return;
    const params = new URLSearchParams({ task_id: taskId });
    params.set("selected_chunk", String(node.chunk_id));
    if (graphRelationEventId != null) {
      params.set("relation_event_id", String(graphRelationEventId));
    }
    navigate(`/novels/${novelId}/graph?${params.toString()}`);
  }, [graphRelationEventId, navigate, node, novelId, taskId]);

  return (
    <AnimatePresence mode="wait">
      {node && config && Icon && (
        <motion.div
          key="node-detail"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          className={cn("overflow-hidden", className)}
        >
          <Card variant="elevated" className="rounded-xl">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Icon className={cn("h-5 w-5", config.colorClass)} />
                  <CardTitle className="text-base font-semibold text-text">
                    {config.label}
                  </CardTitle>
                </div>
                {onClose && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={onClose}
                    className="h-8 w-8 p-0"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </CardHeader>

            <CardContent className="space-y-4">
              <div>
                <p className="text-sm text-text">{node.event}</p>
                <div className="mt-2 flex items-center gap-4 text-xs text-text-muted">
                  <span>第 {node.chunk_id} 块</span>
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

              {node.characters && node.characters.length > 0 && (
                <div>
                  <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-text-muted">
                    <Users className="h-3.5 w-3.5" />
                    <span>涉及角色</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {node.characters.map((char) => (
                      <Badge
                        key={char}
                        variant="secondary"
                        className="cursor-pointer hover:bg-primary/20"
                        onClick={() => handleCharacterClick(char)}
                      >
                        {char}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {(node.is_pivot || node.is_cliffhanger) && (
                <div className="flex gap-2">
                  {node.is_pivot && (
                    <Badge variant="outline" className="gap-1 border-chart-negative text-chart-negative">
                      <Zap className="h-3 w-3" />
                      转折点
                    </Badge>
                  )}
                  {node.is_cliffhanger && (
                    <Badge variant="outline" className="gap-1 border-chart-3 text-chart-3">
                      <HelpCircle className="h-3 w-3" />
                      悬念点
                    </Badge>
                  )}
                </div>
              )}

              {node.character_entries && node.character_entries.length > 0 && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-chart-positive">
                    <User className="h-3.5 w-3.5" />
                    <span>角色登场</span>
                  </div>
                  <p className="mb-2 text-xs leading-5 text-text-muted">
                    这是 timeline 基于稳定 lifecycle 标出的首次登场节点，不是页面侧临时推断结果。
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {node.character_entries.map((char) => (
                      <Badge
                        key={char}
                        variant="secondary"
                        className="cursor-pointer bg-chart-positive/10 text-chart-positive hover:bg-chart-positive/20"
                        onClick={() => handleCharacterClick(char)}
                      >
                        {char}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {node.character_exits && node.character_exits.length > 0 && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-chart-negative">
                    <UserMinus className="h-3.5 w-3.5" />
                    <span>角色退场</span>
                  </div>
                  <p className="mb-2 text-xs leading-5 text-text-muted">
                    这里表达的是稳定 lifecycle 的最后活跃节点，便于和 graph page 的角色状态联动查看。
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {node.character_exits.map((char) => (
                      <Badge
                        key={char}
                        variant="secondary"
                        className="cursor-pointer bg-chart-negative/10 text-chart-negative hover:bg-chart-negative/20"
                        onClick={() => handleCharacterClick(char)}
                      >
                        {char}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {node.relation_changes && node.relation_changes.length > 0 && (
                <div>
                  <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-chart-2">
                    <Link2 className="h-3.5 w-3.5" />
                    <span>关系变化</span>
                  </div>
                  <div className="space-y-2">
                    {node.relation_changes.map((rc, i) => (
                      <div
                        key={rc.relation_event_id ?? i}
                        className={cn(
                          "rounded-md p-3 text-xs",
                          rc.relation_event_id != null && rc.relation_event_id === selectedRelationEventId
                            ? "border border-primary/30 bg-primary/5"
                            : "bg-surface-hover"
                        )}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{rc.from_char}</span>
                          <ArrowRight className="h-3 w-3 text-text-muted" />
                          <span className="font-medium">{rc.to_char}</span>
                          <Badge variant="outline" className="text-[10px]">
                            {rc.relation_type}
                          </Badge>
                          <Badge variant="secondary" className="text-[10px]">
                            {rc.change_type}
                          </Badge>
                          {rc.relation_event_id != null ? (
                            <Badge variant="outline" className="text-[10px]">
                              事件 #{rc.relation_event_id}
                            </Badge>
                          ) : null}
                          {rc.directionality ? (
                            <Badge variant="outline" className="text-[10px]">
                              {rc.directionality}
                            </Badge>
                          ) : null}
                          {rc.confidence != null ? (
                            <Badge variant="outline" className="text-[10px]">
                              置信 {Math.round(rc.confidence * 100)}%
                            </Badge>
                          ) : null}
                        </div>
                        {rc.evidence ? (
                          <p className="mt-2 leading-5 text-text-muted">{rc.evidence}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
