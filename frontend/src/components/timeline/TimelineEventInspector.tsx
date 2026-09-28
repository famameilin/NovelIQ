import { useCallback, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowRight, GitBranch, MapPin, Users, X } from "lucide-react";

import type {
  TimelineEventCausalEdge, TimelineEventForeshadowingEdge, TimelineEventNode, TimelineEventParticipant,
} from "@/api/types";
import { AnalysisViewSwitcher } from "@/components/common/AnalysisViewSwitcher";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { PagedControls } from "@/components/common/PagedControls";
import { useCompactAnalysisViewport } from "@/hooks/useCompactAnalysisViewport";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { paginateText } from "@/lib/paginateText";
import { buildGraphUrl } from "@/pages/graph/graphPageNavigation";
import { buildEventTreeUrl } from "@/pages/eventTrees/eventTreeNavigation";
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

type DetailView = "overview" | "participants" | "causal" | "foreshadowing" | "metrics";
const ROLE_LABELS: Record<string, string> = {
  protagonist: "主要人物", supporting: "协助者", observer: "见证者", subject: "行动主体",
  object: "行动对象", helper: "帮助者", opponent: "阻碍者", sender: "推动者", receiver: "承接者",
};
const STATUS_LABELS: Record<string, string> = {
  open: "待回收", reinforced: "持续强化", likely_paid_off: "疑似回收", archived: "已归档",
};

function roleLabel(role: string): string {
  const value = role.trim();
  if (!value) return "参与者";
  if (/^[\u4e00-\u9fff]/.test(value)) return value;
  return ROLE_LABELS[value.toLowerCase()] ?? "参与者";
}

interface ParticipantGroup { name: string; type: string; roles: string[] }

/** 同一实体的重复抽取记录合并职责，地点不混入角色。 */
function groupParticipants(participants: TimelineEventParticipant[]): ParticipantGroup[] {
  const groups = new Map<string, ParticipantGroup>();
  participants.forEach((participant) => {
    const name = participant.name ?? participant.entity?.name ?? "未命名实体";
    const type = (participant.entity_type ?? participant.entity?.entity_type ?? "character").toLowerCase();
    const key = `${type}:${participant.entity_id ?? participant.entity?.entity_id ?? name}`;
    const group = groups.get(key) ?? { name, type, roles: [] };
    const role = roleLabel(participant.role);
    if (!group.roles.includes(role)) group.roles.push(role);
    groups.set(key, group);
  });
  return [...groups.values()];
}

/** 固定页签内切换信息组，长文本与集合以显式分页完整呈现。 */
export function TimelineEventInspector({
  node, nodes = [], novelId, taskId, causalEdges = [], foreshadowingEdges = [],
  onClose, onSelectChapter, onSelectTree, className,
}: TimelineEventInspectorProps) {
  const navigate = useNavigate();
  const [view, setView] = useState<DetailView>("overview");
  const [page, setPage] = useState(1);
  const [descriptionPage, setDescriptionPage] = useState(1);
  const compact = useCompactAnalysisViewport();
  const eventLabels = useMemo(() => {
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
  const causalLinks = [...new Map(causalEdges
    .filter((edge) => treeEventIds.has(edge.target_event_id) || treeEventIds.has(edge.source_event_id))
    .map((edge) => [edge.edge_id, edge])).values()];
  const relatedForeshadowing = foreshadowingEdges.filter((edge) =>
    treeEventIds.has(edge.root_event_id) ||
    (edge.payoff_event_id != null && treeEventIds.has(edge.payoff_event_id)));
  const rawParticipants = node.participants.length > 0
    ? node.participants
    : node.character_names.map((name) => ({ name, role: "", entity_type: "character" }));
  const grouped = groupParticipants(rawParticipants);
  const characters = grouped.filter((item) => item.type === "character");
  const locations = grouped.filter((item) => item.type === "location" || item.type === "place");
  const otherEntities = grouped.filter((item) => !characters.includes(item) && !locations.includes(item));
  const summaryPassages = paginateText(node.summary, compact ? 120 : 220);
  const pageCount = view === "overview" ? summaryPassages.length
    : view === "participants" ? Math.ceil(characters.length / 6)
      : view === "causal" ? Math.ceil(causalLinks.length / 3)
        : view === "foreshadowing" ? relatedForeshadowing.length
          : Math.ceil(node.main_chain.length / 10);
  const currentPage = Math.min(page, Math.max(pageCount, 1));
  const selectedForeshadowing = relatedForeshadowing[currentPage - 1];
  const descriptionPassages = selectedForeshadowing ? paginateText(selectedForeshadowing.description, 200) : [];
  const currentDescriptionPage = Math.min(descriptionPage, Math.max(descriptionPassages.length, 1));

  const handleSelectChapter = useCallback(() => {
    if (onSelectChapter) onSelectChapter(node.anchor_chapter_id);
    else navigate(buildGraphUrl(novelId, taskId, { chapterId: node.anchor_chapter_id }));
  }, [navigate, node.anchor_chapter_id, novelId, onSelectChapter, taskId]);
  const presentation = getTimelineNodePresentation(
    "event", node.level === 1 ? "root" : node.level === 2 ? "main" : "secondary",
  );
  const Icon = presentation.icon;

  return (
    <motion.div key={node.tree_id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }} className={cn("h-full", className)}>
      <DashboardCardShell title="事件详情" icon={<Icon className={cn("h-4 w-4", presentation.iconClassName)} aria-hidden="true" />}
        accent={presentation.accent} className="h-full" contentClassName="flex h-full flex-col" bodyClassName="min-h-0 flex-1 gap-3"
        headerRight={onClose ? <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0" aria-label="关闭事件详情"><X className="h-4 w-4" /></Button> : undefined}>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{node.level === 1 ? "核心事件" : node.level === 2 ? "主要事件" : "一般事件"}</Badge>
              <Badge variant="outline">{node.phase_name}</Badge>
            </div>
            <h2 className="mt-1 text-lg font-semibold leading-6 text-text">{node.title || node.summary}</h2>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => navigate(buildEventTreeUrl(novelId, taskId, { treeId: node.tree_id, eventId: node.root_event_id }))}>
              查看事件树
            </Button>
            <Button variant="outline" size="sm" onClick={handleSelectChapter}>
              在图谱中定位第 {node.anchor_chapter_id} 章
            </Button>
          </div>
        </div>
        <AnalysisViewSwitcher value={view} onValueChange={(next) => { setView(next); setPage(1); setDescriptionPage(1); }}
          label="事件详情内容" options={[
            { value: "overview", label: "事件概况" },
            { value: "participants", label: `参与实体 ${grouped.length}` },
            { value: "causal", label: `因果联系 ${causalLinks.length}` },
            { value: "foreshadowing", label: `关联伏笔 ${relatedForeshadowing.length}` },
            { value: "metrics", label: "分析数据" },
          ]} />
        <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border/70 bg-surface/70 p-4">
          {view === "overview" && <div className="flex h-full min-h-0 flex-col gap-3">
            <section className="shrink-0 rounded-lg border border-border/60 bg-surface-hover/45 px-3 py-2">
              <h3 className="text-xs font-medium text-text-muted">事件摘要</h3>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-text">{summaryPassages[currentPage - 1] ?? "暂无事件摘要"}</p>
              <PagedControls page={currentPage} pageCount={pageCount} onPageChange={setPage} label="事件摘要" />
            </section>
            <dl className="grid shrink-0 grid-cols-3 gap-2 text-sm">
              <div className="rounded-lg bg-surface-hover/55 px-3 py-2"><dt className="flex items-center gap-1.5 text-xs text-text-muted"><MapPin className="h-3.5 w-3.5" />发生位置</dt><dd className="mt-1 font-medium text-text">{node.start_chapter_id === node.end_chapter_id ? `第 ${node.anchor_chapter_id} 章` : `第 ${node.start_chapter_id} 至 ${node.end_chapter_id} 章`}</dd></div>
              <div className="rounded-lg bg-surface-hover/55 px-3 py-2"><dt className="text-xs text-text-muted">全书位置</dt><dd className="mt-1 font-medium text-text">约 {Math.round(node.progress * 100)}%</dd></div>
              <div className="rounded-lg bg-surface-hover/55 px-3 py-2"><dt className="text-xs text-text-muted">重要性</dt><dd className="mt-1 font-medium text-text">{node.importance_score.toFixed(2)}</dd></div>
            </dl>
            <div className="grid min-h-0 flex-1 grid-cols-2 gap-3">
              <section className="flex min-h-0 flex-col rounded-lg border border-border/60 bg-surface-hover/35 p-3">
                <h3 className="text-xs font-medium text-text-muted">参与角色 · {characters.length} 位</h3>
                <div className="mt-2 grid min-h-0 flex-1 auto-rows-fr gap-1.5">
                  {characters.length > 0 ? characters.slice(0, 3).map((item) => (
                    <div key={`${item.type}-${item.name}`} className="flex min-h-0 items-center justify-between gap-2 rounded-md bg-surface/75 px-2 py-1 text-xs">
                      <span className="truncate font-medium text-text" title={item.name}>{item.name}</span>
                      <span className="shrink-0 text-text-muted">{item.roles[0]}</span>
                    </div>
                  )) : <p className="text-xs text-text-muted">暂无参与角色</p>}
                  {characters.length > 3 && <p className="text-xs text-text-muted">其余 {characters.length - 3} 位可在“参与实体”查看</p>}
                </div>
              </section>
              <section className="flex min-h-0 flex-col rounded-lg border border-border/60 bg-surface-hover/35 p-3">
                <h3 className="text-xs font-medium text-text-muted">关联结构</h3>
                <dl className="mt-2 grid min-h-0 flex-1 auto-rows-fr gap-1.5 text-xs">
                  <div className="flex items-center justify-between rounded-md bg-surface/75 px-2 py-1"><dt className="text-text-muted">因果联系</dt><dd className="font-medium text-text">{causalLinks.length} 条</dd></div>
                  <div className="flex items-center justify-between rounded-md bg-surface/75 px-2 py-1"><dt className="text-text-muted">关联伏笔</dt><dd className="font-medium text-text">{relatedForeshadowing.length} 条</dd></div>
                  <div className="flex items-center justify-between rounded-md bg-surface/75 px-2 py-1"><dt className="text-text-muted">主线 / 旁支</dt><dd className="font-medium text-text">{node.main_chain.length} / {node.secondary_groups.length}</dd></div>
                </dl>
              </section>
            </div>
          </div>}
          {view === "participants" && <div className="flex h-full flex-col gap-3">
            <h3 className="flex items-center gap-2 text-sm font-medium text-text"><Users className="h-4 w-4 text-chart-3" />涉及角色</h3>
            {characters.length > 0 ? <div className="grid grid-cols-2 gap-2">
              {characters.slice((currentPage - 1) * 6, currentPage * 6).map((item) => (
                <div key={`${item.type}-${item.name}`} className="rounded-lg bg-surface-hover/55 px-3 py-2 text-sm">
                  <span className="font-medium text-text">{item.name}</span>
                  <span className="ml-2 text-xs text-text-muted">{item.roles.join("、")}</span>
                </div>
              ))}
            </div> : <p className="text-sm text-text-muted">暂无涉及角色</p>}
            {locations.length > 0 && <p className="text-sm text-text-muted">涉及地点：{locations.map((item) => item.name).join("、")}</p>}
            {otherEntities.length > 0 && <p className="text-sm text-text-muted">其他实体：{otherEntities.map((item) => item.name).join("、")}</p>}
            <PagedControls page={currentPage} pageCount={pageCount} onPageChange={setPage} label="涉及角色" />
          </div>}
          {view === "causal" && <div className="flex h-full flex-col gap-3">
            <h3 className="flex items-center gap-2 text-sm font-medium text-text"><GitBranch className="h-4 w-4 text-chart-4" />因果联系</h3>
            {causalLinks.length > 0 ? causalLinks.slice((currentPage - 1) * 3, currentPage * 3).map((edge) => (
              <div key={edge.edge_id} className="rounded-lg border border-border/60 bg-surface-hover/55 p-3 text-sm">
                <div className="flex items-center gap-2 text-text">
                  <span className="min-w-0 flex-1">{eventLabels.get(edge.source_event_id) ?? `第 ${edge.source_chapter_id} 章事件`}</span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-text-muted" />
                  <span className="min-w-0 flex-1 text-right">{eventLabels.get(edge.target_event_id) ?? `第 ${edge.target_chapter_id} 章事件`}</span>
                </div>
                <p className="mt-1 text-xs text-text-muted">{edge.is_active ? "当前有效" : "已经失效"} · 证据 {edge.evidence.length} 条{edge.expired_at ? ` · 失效日期 ${new Date(edge.expired_at).toLocaleDateString("zh-CN")}` : ""}</p>
              </div>
            )) : <p className="flex flex-1 items-center justify-center text-sm text-text-muted">暂无直接因果联系</p>}
            <PagedControls page={currentPage} pageCount={pageCount} onPageChange={setPage} label="因果联系" />
          </div>}
          {view === "foreshadowing" && <div className="flex min-h-0 flex-1 flex-col justify-center gap-3">
            <h3 className="text-sm font-medium text-text">关联伏笔</h3>
            {selectedForeshadowing ? <div className="rounded-lg bg-surface-hover/55 p-4">
              <div className="flex items-center gap-2"><Badge variant="outline">{STATUS_LABELS[selectedForeshadowing.status.trim().toLowerCase()] ?? "状态待确认"}</Badge><span className="text-xs text-text-muted">第 {selectedForeshadowing.first_chapter_id} 至 {selectedForeshadowing.last_chapter_id} 章</span></div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-text-muted">{descriptionPassages[currentDescriptionPage - 1]}</p>
              <PagedControls page={currentDescriptionPage} pageCount={descriptionPassages.length} onPageChange={setDescriptionPage} label="伏笔描述" />
            </div> : <p className="flex flex-1 items-center justify-center text-sm text-text-muted">暂无关联伏笔</p>}
            <PagedControls page={currentPage} pageCount={pageCount} onPageChange={(next) => { setPage(next); setDescriptionPage(1); }} label="关联伏笔" />
          </div>}
          {view === "metrics" && <div className="flex h-full flex-col justify-center gap-4">
            <dl className="grid grid-cols-4 gap-3 text-sm">
              {[
                ["重要性得分", node.importance_score.toFixed(2)], ["覆盖章节", `${node.chapter_ids.length} 章`],
                ["字符范围", `${node.char_start.toLocaleString()} 至 ${node.char_end.toLocaleString()}`],
                ["进度范围", `${(node.start_progress * 100).toFixed(1)}% 至 ${(node.end_progress * 100).toFixed(1)}%`],
                ["旁支数量", `${node.secondary_groups.length} 组`], ["因果计数", `前因 ${node.causal_in} · 后果 ${node.causal_out}`],
              ].map(([label, value]) => <div key={label} className="rounded-lg bg-surface-hover/55 p-3"><dt className="text-xs text-text-muted">{label}</dt><dd className="mt-1 font-medium text-text">{value}</dd></div>)}
            </dl>
            <section><h3 className="text-sm font-medium text-text">主线步骤</h3><div className="mt-2 flex flex-wrap gap-2">
              {node.main_chain.length > 0 ? node.main_chain.slice((currentPage - 1) * 10, currentPage * 10).map((eventId, index) => (
                <button key={eventId} type="button" onClick={() => onSelectTree?.(eventId)} className="rounded-md border border-border/60 px-3 py-1.5 text-xs text-text hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45">第 {(currentPage - 1) * 10 + index + 1} 步</button>
              )) : <span className="text-sm text-text-muted">暂无主线步骤</span>}
            </div></section>
            <PagedControls page={currentPage} pageCount={pageCount} onPageChange={setPage} label="主线步骤" />
          </div>}
        </div>
      </DashboardCardShell>
    </motion.div>
  );
}
