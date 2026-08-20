/**
 * TimelineNodeDetail - 事件森林节点详情（2026-08-20 一树一节点版）
 *
 * 旧合同的 graph_changes / lifecycle_events / plot_flags / score_breakdown 已彻底移除
 * 新详情：summary + participants + chapter 区间 + char 区间 + main_chain + secondary_groups + causal 前因后果 + 证据占位
 */

import { useCallback, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowRight, ChevronDown, ChevronUp, Link2, MapPin, Users, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import type {
  TimelineEventCausalEdge,
  TimelineEventForeshadowingEdge,
  TimelineEventNode,
} from "@/api/types";
import { cn } from "@/lib/cn";

import { getTimelineNodePresentation } from "./timelineNodePresentation";

export interface TimelineNodeDetailProps {
  node: TimelineEventNode | null;
  nodes?: TimelineEventNode[];
  novelId: string;
  taskId: string;
  causalEdges?: TimelineEventCausalEdge[];
  foreshadowingEdges?: TimelineEventForeshadowingEdge[];
  derivedOrder?: string[];
  onClose?: () => void;
  onSelectChapter?: (chapterId: number) => void;
  onSelectTree?: (treeId: string) => void;
  className?: string;
  // ── 过渡期兼容：旧页面仍传这些，忽略 ──
  atomicNodes?: unknown;
  selectedGraphChangeId?: string | null;
  onSelectAtomicNode?: unknown;
}

function resolveCauseRole(level: 1 | 2 | 3): "root" | "main" | "secondary" {
  if (level === 1) return "root";
  if (level === 2) return "main";
  return "secondary";
}

export function TimelineNodeDetail({
  node,
  nodes = [],
  novelId,
  taskId,
  causalEdges = [],
  foreshadowingEdges = [],
  derivedOrder = [],
  onClose,
  onSelectChapter,
  onSelectTree,
  className,
}: TimelineNodeDetailProps) {
  const navigate = useNavigate();
  const [secondaryOpen, setSecondaryOpen] = useState(true);
  const [causalOpen, setCausalOpen] = useState(true);

  const presentation = useMemo(() => {
    if (!node) return null;
    return getTimelineNodePresentation("event", resolveCauseRole(node.level));
  }, [node]);

  const Icon = presentation?.icon;

  const chapterRangeLabel = useMemo(() => {
    if (!node) return "";
    const rec = node as unknown as Record<string, unknown>;
    const start = (rec["start_chapter_id"] as number) ?? (rec["anchor_chapter_id"] as number) ?? 0;
    const end = (rec["end_chapter_id"] as number) ?? (rec["anchor_chapter_id"] as number) ?? 0;
    const anchor = (rec["anchor_chapter_id"] as number) ?? start ?? 0;
    if (start !== end) {
      return `${start} – ${end} 章`;
    }
    return `第 ${anchor} 章`;
  }, [node]);

  const chapterIdsLabel = useMemo(() => {
    if (!node) return "—";
    const rec = node as unknown as Record<string, unknown>;
    const ids = (rec["chapter_ids"] as number[] | undefined) ?? [];
    if (ids.length === 0) return "—";
    if (ids.length <= 8) return ids.join(", ");
    return `${ids.slice(0, 8).join(", ")} … 等 ${ids.length} 章`;
  }, [node]);

  // main_chain 按 derivedOrder 排序，若无 derivedOrder 则保持原序；尝试从 nodes 解析 description
  const orderedMainChain = useMemo(() => {
    if (!node) return [];
    const rec = node as unknown as Record<string, unknown>;
    const rawChain = (rec["main_chain"] as string[] | undefined) ?? [];
    const chain = [...rawChain];
    if (derivedOrder.length > 0) {
      const orderIndex = new Map(derivedOrder.map((id, idx) => [id, idx] as const));
      chain.sort((a, b) => {
        const ai = orderIndex.get(a);
        const bi = orderIndex.get(b);
        if (ai != null && bi != null) return ai - bi;
        if (ai != null) return -1;
        if (bi != null) return 1;
        return 0;
      });
    }
    // 建立 event_id -> node 标题映射，用于展示 description
    const titleByEventId = new Map<string, string>();
    nodes.forEach((n) => {
      titleByEventId.set(n.root_event_id, n.title ?? n.summary);
      n.main_chain.forEach((eid) => {
        if (!titleByEventId.has(eid)) titleByEventId.set(eid, eid);
      });
      n.secondary_groups.forEach((g) => {
        g.branch.forEach((eid) => {
          if (!titleByEventId.has(eid)) titleByEventId.set(eid, eid);
        });
      });
    });
    return chain.map((eventId) => ({
      eventId,
      label: titleByEventId.get(eventId) ?? eventId,
    }));
  }, [node, derivedOrder, nodes]);

  // causal 前因后果：过滤 source/target 为本树事件（tree_id, root_event_id, main_chain, secondary branch）
  const { causalInEdges, causalOutEdges } = useMemo(() => {
    if (!node) return { causalInEdges: [] as TimelineEventCausalEdge[], causalOutEdges: [] as TimelineEventCausalEdge[] };
    const rec = node as unknown as Record<string, unknown>;
    const rootId = (rec["root_event_id"] as string) ?? (rec["tree_id"] as string) ?? "";
    const mainChain = (rec["main_chain"] as string[] | undefined) ?? [];
    const secondaryGroups = (rec["secondary_groups"] as Array<{ target_event_id: string; branch: string[] }> | undefined) ?? [];
    const treeId = (rec["tree_id"] as string) ?? rootId;
    const treeEventIds = new Set<string>([rootId, ...mainChain]);
    secondaryGroups.forEach((g) => {
      g.branch.forEach((eid) => treeEventIds.add(eid));
      treeEventIds.add(g.target_event_id);
    });
    // 也包含 tree_id 本身若边直接指向 tree_id（兼容）
    treeEventIds.add(treeId);
    const inEdges = causalEdges.filter((e) => treeEventIds.has(e.target_event_id));
    const outEdges = causalEdges.filter((e) => treeEventIds.has(e.source_event_id));
    return { causalInEdges: inEdges, causalOutEdges: outEdges };
  }, [node, causalEdges]);

  const relatedForeshadowing = useMemo(() => {
    if (!node) return [] as TimelineEventForeshadowingEdge[];
    const rec = node as unknown as Record<string, unknown>;
    const rootId = (rec["root_event_id"] as string) ?? "";
    const mainChain = (rec["main_chain"] as string[] | undefined) ?? [];
    const secondaryGroups = (rec["secondary_groups"] as Array<{ branch: string[] }> | undefined) ?? [];
    const treeEventIds = new Set<string>([rootId, ...mainChain]);
    secondaryGroups.forEach((g) => g.branch.forEach((eid) => treeEventIds.add(eid)));
    return foreshadowingEdges.filter(
      (f) => treeEventIds.has(f.setup_event_id) || (f.payoff_event_id && treeEventIds.has(f.payoff_event_id))
    );
  }, [node, foreshadowingEdges]);

  const handleGoToEvidence = useCallback(() => {
    if (!node) return;
    // 优先跳转到本树锚点：timeline?tree_id= & event_id=，保留 task_id
    const rec = node as unknown as Record<string, unknown>;
    const treeId = (rec["tree_id"] as string) ?? (rec["node_id"] as string) ?? "";
    const rootId = (rec["root_event_id"] as string) ?? "";
    const params = new URLSearchParams({ task_id: taskId, tree_id: treeId });
    if (rootId) params.set("event_id", rootId);
    navigate(`/novels/${novelId}/timeline?${params.toString()}`);
  }, [navigate, node, novelId, taskId]);

  const handleSelectAnchorChapter = useCallback(() => {
    if (!node) return;
    const rec = node as unknown as Record<string, unknown>;
    const anchor = (rec["anchor_chapter_id"] as number) ?? 0;
    if (onSelectChapter) {
      onSelectChapter(anchor);
      return;
    }
    // 默认回退：跳转到章节视图（若无专门章节页则留在 timeline 锚点）
    navigate(`/novels/${novelId}/chapters?task_id=${taskId}&chapter=${anchor}`);
  }, [navigate, node, novelId, onSelectChapter, taskId]);

  if (!node || !presentation || !Icon) {
    return (
      <div
        className={cn(
          "flex h-full min-h-[240px] items-center justify-center rounded-2xl border border-dashed border-border/60 bg-surface/50 text-sm text-text-muted",
          className
        )}
      >
        在时间轴中选择一个节点后查看详情。
      </div>
    );
  }

  // 兼容旧节点字段缺失：统一兜底，避免旧单测崩溃
  const recNode = node as unknown as Record<string, unknown>;
  const safeTreeId = (recNode["tree_id"] as string) ?? (recNode["node_id"] as string) ?? "unknown";
  const safeSummary = (recNode["summary"] as string) ?? "";
  const safeTitle = (recNode["title"] as string | undefined) ?? undefined;
  const safeProgress = (recNode["progress"] as number) ?? 0;
  const safeImportance = (recNode["importance_score"] as number) ?? 0;
  const safeLevel = (recNode["level"] as number) ?? 3;
  const safePhase = (recNode["phase_name"] as string) ?? "";
  const safeParticipants = (recNode["participants"] as Array<Record<string, unknown>> | undefined) ?? [];
  const safeCharacterNames = (recNode["character_names"] as string[] | undefined) ?? (recNode["characters"] as string[] | undefined) ?? [];
  const safeChapterIds = (recNode["chapter_ids"] as number[] | undefined) ?? [];
  const safeAnchorChapterId = (recNode["anchor_chapter_id"] as number) ?? 0;
  const safeAnchorOrder = (recNode["anchor_chapter_order"] as number) ?? safeAnchorChapterId;
  const safeStartChapter = (recNode["start_chapter_id"] as number) ?? safeAnchorChapterId;
  const safeEndChapter = (recNode["end_chapter_id"] as number) ?? safeAnchorChapterId;
  const safeCharStart = (recNode["char_start"] as number) ?? 0;
  const safeCharEnd = (recNode["char_end"] as number) ?? safeCharStart;
  const safeStartProgress = (recNode["start_progress"] as number) ?? safeProgress;
  const safeEndProgress = (recNode["end_progress"] as number) ?? safeProgress;
  const safeCausalOut = (recNode["causal_out"] as number) ?? 0;
  const safeCausalIn = (recNode["causal_in"] as number) ?? 0;
  const safeSecondaryGroups = (recNode["secondary_groups"] as Array<{ target_event_id: string; branch: string[] }> | undefined) ?? [];

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={safeTreeId}
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
          bodyClassName="gap-5"
        >
          {/* 顶部 summary 全文 */}
          <div>
            <p className="text-sm leading-6 text-text">{safeSummary || "暂无摘要"}</p>
            {safeTitle && safeTitle !== safeSummary ? (
              <p className="mt-1 text-xs text-text-muted">标题：{safeTitle}</p>
            ) : null}
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-muted">
              <Badge variant="outline" className="gap-1">
                <MapPin className="h-3 w-3" />
                {chapterRangeLabel}
              </Badge>
              <span>
                进度 {Math.round(safeProgress * 100)}% · 重要性 {safeImportance.toFixed(1)} · level {safeLevel}
              </span>
              <span>
                {safePhase} · {safeTreeId}
              </span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={handleGoToEvidence}>
                查看证据
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" onClick={handleSelectAnchorChapter}>
                跳转锚点章 {safeAnchorChapterId}
              </Button>
            </div>
          </div>

          {/* participants */}
          <div>
            <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-text-muted">
              <Users className="h-3.5 w-3.5" />
              <span>参与者 {safeParticipants.length > 0 ? `· ${safeParticipants.length} 人` : ""}</span>
            </div>
            {safeParticipants.length === 0 ? (
              <p className="text-xs text-text-muted">暂无参与者标注</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {safeParticipants.map((p, idx) => {
                  const name = String((p as Record<string, unknown>)["name"] ?? `参与者${idx + 1}`);
                  const role = String((p as Record<string, unknown>)["role"] ?? "");
                  const entityId = (p as Record<string, unknown>)["entity_id"] != null ? String((p as Record<string, unknown>)["entity_id"]) : null;
                  return (
                    <Badge
                      key={`${name}-${idx}`}
                      variant="secondary"
                      className="gap-1"
                      title={entityId ? `entity ${entityId}` : undefined}
                    >
                      <span className="font-medium">{name}</span>
                      {role ? <span className="text-[11px] text-text-muted">· {role}</span> : null}
                    </Badge>
                  );
                })}
              </div>
            )}
            {safeCharacterNames.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {safeCharacterNames.map((name) => (
                  <Badge key={name} variant="outline" className="text-[11px]">
                    {name}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>

          {/* 章节与字符区间 */}
          <div className="rounded-xl border border-border/40 bg-surface/40 p-3">
            <div className="grid grid-cols-1 gap-2 text-xs md:grid-cols-2">
              <div>
                <span className="font-medium text-text-muted">章节区间</span>
                <p className="mt-1 font-mono text-text">{chapterIdsLabel}</p>
                <p className="text-[11px] text-text-muted">
                  锚点章 {safeAnchorChapterId}（order {safeAnchorOrder}）· 跨度 {safeStartChapter}–{safeEndChapter}
                </p>
              </div>
              <div>
                <span className="font-medium text-text-muted">字符区间</span>
                <p className="mt-1 font-mono text-text">
                  {safeCharStart.toLocaleString()} ~ {safeCharEnd.toLocaleString()}
                </p>
                <p className="text-[11px] text-text-muted">
                  长 {(safeCharEnd - safeCharStart).toLocaleString()} 字符 · 覆盖 {safeChapterIds.length} 章
                </p>
              </div>
            </div>
            <div className="mt-2 text-[11px] text-text-muted">
              start_progress {safeStartProgress.toFixed(3)} · end_progress {safeEndProgress.toFixed(3)} · progress{" "}
              {safeProgress.toFixed(3)}
            </div>
          </div>

          {/* main_chain */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-medium text-text-muted">主链（{orderedMainChain.length}）· 按派生顺序</span>
              <Badge variant="outline" className="text-[11px]">
                因果出度 {safeCausalOut} · 入度 {safeCausalIn}
              </Badge>
            </div>
            {orderedMainChain.length === 0 ? (
              <p className="text-xs text-text-muted">该树暂无主链数据</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {orderedMainChain.map((item, idx) => (
                  <Badge
                    key={item.eventId}
                    variant="secondary"
                    className="cursor-pointer gap-1 hover:bg-primary/15"
                    onClick={() => onSelectTree?.(item.eventId)}
                    title={item.eventId}
                  >
                    <span className="text-[11px] font-medium">{idx + 1}.</span>
                    <span className="max-w-[160px] truncate text-xs">{item.label}</span>
                  </Badge>
                ))}
              </div>
            )}
          </div>

          {/* secondary_groups 可折叠 */}
          <div>
            <button
              type="button"
              onClick={() => setSecondaryOpen((v) => !v)}
              className="flex w-full items-center justify-between rounded-lg border border-border/40 bg-surface/30 px-3 py-2 text-left"
            >
              <span className="flex items-center gap-1.5 text-xs font-medium text-text-muted">
                <Link2 className="h-3.5 w-3.5" />
                旁支分支 {safeSecondaryGroups.length > 0 ? `· ${safeSecondaryGroups.length} 组` : "· 无"}
              </span>
              {secondaryOpen ? <ChevronUp className="h-4 w-4 text-text-muted" /> : <ChevronDown className="h-4 w-4 text-text-muted" />}
            </button>
            {secondaryOpen ? (
              <div className="mt-2 space-y-2">
                {safeSecondaryGroups.length === 0 ? (
                  <p className="px-1 text-xs text-text-muted">该树暂无旁支</p>
                ) : (
                  safeSecondaryGroups.map((group) => (
                    <div key={group.target_event_id} className="rounded-lg bg-surface-hover p-3">
                      <div className="flex items-center gap-2 text-xs">
                        <span className="font-medium text-text">指向 {group.target_event_id}</span>
                        <Badge variant="outline" className="text-[10px]">
                          分支 {group.branch.length} 步
                        </Badge>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {group.branch.map((eid, idx) => (
                          <Badge key={`${group.target_event_id}-${eid}-${idx}`} variant="outline" className="text-[11px]">
                            {eid}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            ) : null}
          </div>

          {/* causal 前因后果 */}
          <div>
            <button
              type="button"
              onClick={() => setCausalOpen((v) => !v)}
              className="flex w-full items-center justify-between rounded-lg border border-border/40 bg-surface/30 px-3 py-2 text-left"
            >
              <span className="text-xs font-medium text-text-muted">因果边 · 入 {causalInEdges.length} / 出 {causalOutEdges.length}</span>
              {causalOpen ? <ChevronUp className="h-4 w-4 text-text-muted" /> : <ChevronDown className="h-4 w-4 text-text-muted" />}
            </button>
            {causalOpen ? (
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <div>
                  <div className="mb-2 text-xs font-medium text-text">前因（入边）</div>
                  {causalInEdges.length === 0 ? (
                    <p className="text-xs text-text-muted">无前因边</p>
                  ) : (
                    <div className="space-y-2">
                      {causalInEdges.map((edge) => (
                        <div
                          key={edge.edge_id}
                          className={cn(
                            "rounded-lg border p-2.5 text-xs",
                            edge.is_active ? "border-primary/20 bg-primary/5" : "border-border/60 bg-surface-hover opacity-60"
                          )}
                        >
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-mono text-[11px]">{edge.source_event_id}</span>
                            <ArrowRight className="h-3 w-3 text-text-muted" />
                            <span className="font-mono text-[11px]">{edge.target_event_id}</span>
                            <Badge variant="outline" className={cn("text-[10px]", !edge.is_active && "border-dashed")}>
                              {edge.is_active ? "活跃" : "已失效"}
                            </Badge>
                          </div>
                          <div className="mt-1 text-[11px] text-text-muted">
                            {edge.source_chapter_id} → {edge.target_chapter_id} 章
                            {edge.expired_at ? ` · 失效于 ${new Date(edge.expired_at).toLocaleDateString()}` : ""}
                          </div>
                          {edge.evidence?.length ? (
                            <div className="mt-1 text-[11px] text-text-muted">证据 {edge.evidence.length} 条</div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <div className="mb-2 text-xs font-medium text-text">后果（出边）</div>
                  {causalOutEdges.length === 0 ? (
                    <p className="text-xs text-text-muted">无后果边</p>
                  ) : (
                    <div className="space-y-2">
                      {causalOutEdges.map((edge) => (
                        <div
                          key={edge.edge_id}
                          className={cn(
                            "rounded-lg border p-2.5 text-xs",
                            edge.is_active ? "border-primary/20 bg-primary/5" : "border-border/60 bg-surface-hover opacity-60"
                          )}
                        >
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-mono text-[11px]">{edge.source_event_id}</span>
                            <ArrowRight className="h-3 w-3 text-text-muted" />
                            <span className="font-mono text-[11px]">{edge.target_event_id}</span>
                            <Badge variant="outline" className={cn("text-[10px]", !edge.is_active && "border-dashed")}>
                              {edge.is_active ? "活跃" : "已失效"}
                            </Badge>
                          </div>
                          <div className="mt-1 text-[11px] text-text-muted">
                            {edge.source_chapter_id} → {edge.target_chapter_id} 章
                            {edge.expired_at ? ` · 失效于 ${new Date(edge.expired_at).toLocaleDateString()}` : ""}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </div>

          {/* 伏笔边占位 */}
          {relatedForeshadowing.length > 0 ? (
            <div>
              <div className="mb-2 text-xs font-medium text-text-muted">关联伏笔</div>
              <div className="space-y-2">
                {relatedForeshadowing.map((f) => (
                  <div key={f.setup_id} className="rounded-lg bg-surface-hover p-3 text-xs">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[10px]">
                        {f.status}
                      </Badge>
                      <Badge variant={f.active ? "secondary" : "outline"} className="text-[10px]">
                        {f.active ? "活跃" : "已归档"}
                      </Badge>
                      <span className="text-text-muted">
                        {f.first_chapter_id} – {f.last_chapter_id} 章
                      </span>
                    </div>
                    <p className="mt-1.5 leading-5 text-text-muted">{f.setup_summary}</p>
                    <p className="mt-1 font-mono text-[11px] text-text-muted">setup {f.setup_event_id} → {f.payoff_event_id ?? "待回收"}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* 证据段落占位 */}
          <div className="rounded-xl border border-dashed border-border/60 bg-surface/30 p-3">
            <div className="text-xs font-medium text-text-muted">证据段落</div>
            <p className="mt-1 text-xs leading-5 text-text-muted">
              本树锚点章 {safeAnchorChapterId}，字符区间 {safeCharStart}–{safeCharEnd}。证据按段落锚点回溯时可在此展示
              anchor_paragraph_ids 列表（当前后端未透出段落粒度证据，保留占位用于后续证据链落地）。
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge variant="outline" className="font-mono text-[11px]">
                chap {safeAnchorChapterId}
              </Badge>
              <Badge variant="outline" className="font-mono text-[11px]">
                chars {safeCharStart}~{safeCharEnd}
              </Badge>
              <Badge variant="outline" className="font-mono text-[11px]">
                chapters {safeChapterIds.length}
              </Badge>
            </div>
          </div>
        </DashboardCardShell>
      </motion.div>
    </AnimatePresence>
  );
}
