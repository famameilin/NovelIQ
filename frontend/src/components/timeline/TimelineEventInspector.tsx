import { useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowRight, GitBranch, MapPin, Users, X } from "lucide-react";

import type {
  TimelineEventCausalEdge,
  TimelineEventForeshadowingEdge,
  TimelineEventNode,
  TimelineEventParticipant,
} from "@/api/types";
import { AnalysisDetails } from "@/components/common/AnalysisDetails";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

import { getTimelineNodePresentation } from "./timelineNodePresentation";

export interface TimelineEventInspectorProps {
  node: TimelineEventNode;
  nodes?: TimelineEventNode[];
  novelId: string;
  taskId: string;
  causalEdges?: TimelineEventCausalEdge[];
  foreshadowingEdges?: TimelineEventForeshadowingEdge[];
  onClose?: () => void;
  onSelectChapter?: (chapterId: number) => void;
  onSelectTree?: (treeId: string) => void;
  className?: string;
}

const PARTICIPANT_ROLE_LABELS: Record<string, string> = {
  protagonist: "主要人物",
  supporting: "协助者",
  observer: "见证者",
  subject: "行动主体",
  object: "行动对象",
  helper: "帮助者",
  opponent: "阻碍者",
  sender: "推动者",
  receiver: "承接者",
};

const FORESHADOW_STATUS_LABELS: Record<string, string> = {
  open: "待回收",
  reinforced: "持续强化",
  likely_paid_off: "疑似回收",
  archived: "已归档",
};

/**
 * 2026-08-31，作用：将事件重要层级转换为中文标签
 * 简要说明：隐藏内部层级编号，只表达用户关心的重要程度
 */
function getImportanceLabel(level: 1 | 2 | 3): string {
  if (level === 1) return "核心事件";
  if (level === 2) return "主要事件";
  return "一般事件";
}

/**
 * 2026-08-31，作用：将参与者职责转换为中文标签
 * 简要说明：已知枚举使用固定名称，中文原值直接保留，未知值使用通用职责
 */
function getParticipantRoleLabel(role: string): string {
  const normalizedRole = role.trim();
  if (!normalizedRole) return "参与者";
  if (/^[\u4e00-\u9fff]/.test(normalizedRole)) return normalizedRole;
  return PARTICIPANT_ROLE_LABELS[normalizedRole.toLowerCase()] ?? "参与者";
}

/**
 * 2026-08-31，作用：将伏笔状态转换为中文标签
 * 简要说明：时间轴关联伏笔与诊断页使用一致的四态语义
 */
function getForeshadowStatusLabel(status: string): string {
  return FORESHADOW_STATUS_LABELS[status.trim().toLowerCase()] ?? "状态待确认";
}

/**
 * 2026-08-31，作用：生成事件章节范围文案
 * 简要说明：单章事件和跨章事件使用不同的自然语言表达
 */
function getChapterRangeLabel(node: TimelineEventNode): string {
  if (node.start_chapter_id === node.end_chapter_id) return `第 ${node.anchor_chapter_id} 章`;
  return `第 ${node.start_chapter_id} 至 ${node.end_chapter_id} 章`;
}

/**
 * 2026-08-31，作用：为因果边解析用户可读的事件名称
 * 简要说明：优先使用事件标题或摘要，无法解析时仅显示对应章节
 */
function getCausalEventLabel(
  eventId: string,
  chapterId: number,
  eventLabelById: ReadonlyMap<string, string>,
): string {
  return eventLabelById.get(eventId) ?? `第 ${chapterId} 章事件`;
}

/**
 * 2026-08-31，作用：展示时间轴选中事件的同屏详情
 * 简要说明：主区呈现摘要、位置、角色和因果联系，技术口径收纳到分析详情
 */
export function TimelineEventInspector({
  node,
  nodes = [],
  novelId,
  taskId,
  causalEdges = [],
  foreshadowingEdges = [],
  onClose,
  onSelectChapter,
  onSelectTree,
  className,
}: TimelineEventInspectorProps) {
  const navigate = useNavigate();
  const eventLabelById = useMemo(() => {
    const labels = new Map<string, string>();
    nodes.forEach((item) => {
      labels.set(item.root_event_id, item.title || item.summary);
      labels.set(item.tree_id, item.title || item.summary);
    });
    return labels;
  }, [nodes]);

  const treeEventIds = useMemo(() => {
    const ids = new Set<string>([node.tree_id, node.root_event_id, ...node.main_chain]);
    node.secondary_groups.forEach((group) => {
      ids.add(group.target_event_id);
      group.branch.forEach((eventId) => ids.add(eventId));
    });
    return ids;
  }, [node]);
  const causalInEdges = causalEdges.filter((edge) => treeEventIds.has(edge.target_event_id));
  const causalOutEdges = causalEdges.filter((edge) => treeEventIds.has(edge.source_event_id));
  const relatedForeshadowing = foreshadowingEdges.filter(
    (edge) =>
      treeEventIds.has(edge.root_event_id) ||
      (edge.payoff_event_id != null && treeEventIds.has(edge.payoff_event_id)),
  );

  const handleSelectAnchorChapter = useCallback(() => {
    if (onSelectChapter) {
      onSelectChapter(node.anchor_chapter_id);
      return;
    }
    navigate(`/novels/${novelId}/chapters?task_id=${taskId}&chapter=${node.anchor_chapter_id}`);
  }, [navigate, node.anchor_chapter_id, novelId, onSelectChapter, taskId]);

  const presentation = getTimelineNodePresentation(
    "event",
    node.level === 1 ? "root" : node.level === 2 ? "main" : "secondary",
  );
  const Icon = presentation.icon;
  const visibleParticipants: TimelineEventParticipant[] =
    node.participants.length > 0
      ? node.participants
      : node.character_names.map((name) => ({ name, role: "", entity_id: null, entity_type: "character" }));

  return (
    <motion.div
      key={node.tree_id}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className={className}
    >
      <DashboardCardShell
        title="事件详情"
        icon={<Icon className={cn("h-4 w-4", presentation.iconClassName)} aria-hidden="true" />}
        accent={presentation.accent}
        headerRight={
          onClose ? (
            <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0" aria-label="关闭事件详情">
              <X className="h-4 w-4" aria-hidden="true" />
            </Button>
          ) : undefined
        }
        bodyClassName="gap-5"
      >
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{getImportanceLabel(node.level)}</Badge>
            <Badge variant="outline">{node.phase_name}</Badge>
          </div>
          <h2 className="mt-3 text-lg font-semibold leading-7 text-text">{node.title || node.summary}</h2>
          {node.title && node.title !== node.summary ? (
            <p className="mt-2 text-sm leading-6 text-text-muted">{node.summary}</p>
          ) : null}
        </div>

        <dl className="grid grid-cols-1 gap-3">
          <div className="rounded-lg bg-surface-hover/55 p-3">
            <dt className="flex items-center gap-1.5 text-xs text-text-muted">
              <MapPin className="h-3.5 w-3.5" aria-hidden="true" />发生位置
            </dt>
            <dd className="mt-1 text-sm font-medium text-text">{getChapterRangeLabel(node)}</dd>
          </div>
          <div className="rounded-lg bg-surface-hover/55 p-3">
            <dt className="text-xs text-text-muted">全书位置</dt>
            <dd className="mt-1 text-sm font-medium text-text">约 {Math.round(node.progress * 100)}%</dd>
          </div>
        </dl>

        <section aria-labelledby="timeline-participants-title">
          <h3 id="timeline-participants-title" className="flex items-center gap-2 text-sm font-medium text-text">
            <Users className="h-4 w-4 text-chart-3" aria-hidden="true" />涉及角色
          </h3>
          {visibleParticipants.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {visibleParticipants.map((participant, index) => (
                <span key={`${participant.name ?? participant.entity?.name ?? "participant"}-${index}`} className="rounded-full border border-border/60 bg-background/60 px-3 py-1.5 text-sm text-text">
                  <span className="font-medium">{participant.name ?? participant.entity?.name ?? "未命名实体"}</span>
                  <span className="ml-1 text-xs text-text-muted">{getParticipantRoleLabel(participant.role)}</span>
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-sm text-text-muted">暂无涉及角色</p>
          )}
        </section>

        <section aria-labelledby="timeline-causal-title">
          <div className="flex items-center justify-between gap-3">
            <h3 id="timeline-causal-title" className="flex items-center gap-2 text-sm font-medium text-text">
              <GitBranch className="h-4 w-4 text-chart-4" aria-hidden="true" />因果联系
            </h3>
            <span className="text-xs text-text-muted">前因 {causalInEdges.length} 条 · 后果 {causalOutEdges.length} 条</span>
          </div>
          {causalInEdges.length + causalOutEdges.length > 0 ? (
            <div className="mt-3 space-y-2">
              {[...causalInEdges, ...causalOutEdges].map((edge) => (
                <div key={edge.edge_id} className={cn("rounded-lg border p-3 text-sm", edge.is_active ? "border-primary/20 bg-primary/5" : "border-border/60 bg-surface-hover/55")}>
                  <div className="flex items-center gap-2 text-text">
                    <span className="min-w-0 flex-1 truncate">{getCausalEventLabel(edge.source_event_id, edge.source_chapter_id, eventLabelById)}</span>
                    <ArrowRight className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate text-right">{getCausalEventLabel(edge.target_event_id, edge.target_chapter_id, eventLabelById)}</span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-text-muted">
                    <span>{edge.is_active ? "当前有效" : "已经失效"}</span>
                    <span>证据 {edge.evidence.length} 条</span>
                    {edge.expired_at ? <span>失效日期 {new Date(edge.expired_at).toLocaleDateString("zh-CN")}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-sm text-text-muted">暂无直接因果联系</p>
          )}
        </section>

        {relatedForeshadowing.length > 0 ? (
          <section aria-labelledby="timeline-foreshadow-title">
            <h3 id="timeline-foreshadow-title" className="text-sm font-medium text-text">关联伏笔</h3>
            <div className="mt-3 space-y-2">
              {relatedForeshadowing.map((item) => (
                <div key={item.root_event_id} className="rounded-lg bg-surface-hover/55 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{getForeshadowStatusLabel(item.status)}</Badge>
                    <span className="text-xs text-text-muted">第 {item.first_chapter_id} 至 {item.last_chapter_id} 章</span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-text-muted">{item.description}</p>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <Button variant="outline" size="sm" onClick={handleSelectAnchorChapter}>查看第 {node.anchor_chapter_id} 章</Button>

        <AnalysisDetails description="事件跨度、位置口径、主线与旁支数量">
          <dl className="grid grid-cols-1 gap-3 text-sm">
            <div><dt className="text-text-muted">重要性得分</dt><dd className="mt-1 font-medium text-text">{node.importance_score.toFixed(2)}</dd></div>
            <div><dt className="text-text-muted">覆盖章节</dt><dd className="mt-1 font-medium text-text">{node.chapter_ids.length} 章</dd></div>
            <div><dt className="text-text-muted">字符范围</dt><dd className="mt-1 font-medium text-text">{node.char_start.toLocaleString()} 至 {node.char_end.toLocaleString()}</dd></div>
            <div><dt className="text-text-muted">进度范围</dt><dd className="mt-1 font-medium text-text">{(node.start_progress * 100).toFixed(1)}% 至 {(node.end_progress * 100).toFixed(1)}%</dd></div>
            <div>
              <dt className="text-text-muted">主线步骤</dt>
              <dd className="mt-1 flex flex-wrap gap-1.5">
                {node.main_chain.length > 0
                  ? node.main_chain.map((eventId, index) => (
                      <button key={eventId} type="button" onClick={() => onSelectTree?.(eventId)} className="rounded-md border border-border/60 px-2 py-1 text-xs text-text hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45">
                        第 {index + 1} 步
                      </button>
                    ))
                  : "—"}
              </dd>
            </div>
            <div><dt className="text-text-muted">旁支数量</dt><dd className="mt-1 font-medium text-text">{node.secondary_groups.length} 组</dd></div>
            <div><dt className="text-text-muted">因果计数</dt><dd className="mt-1 font-medium text-text">前因 {node.causal_in} 条 · 后果 {node.causal_out} 条</dd></div>
          </dl>
        </AnalysisDetails>
      </DashboardCardShell>
    </motion.div>
  );
}
