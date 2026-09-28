import { ArrowRight, BookOpen, Link2 } from "lucide-react";

import type { EventForestNode, EventForestResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const FORESHADOW_LABELS: Record<string, string> = {
  open: "待回收", reinforced: "持续强化", likely_paid_off: "疑似回收",
};

interface EventTreeInspectorProps {
  node: EventForestNode;
  foreshadow: EventForestResponse["foreshadowing_edges"][number] | null;
  causalEdges: EventForestResponse["causal_edges"];
  nodes: Map<string, EventForestNode>;
  onReadSource: () => void;
  onSelectRelatedEvent: (eventId: string) => void;
}

/** 选中节点的证据与关系集中在画布旁，不让详情把整页向下撑长 */
export function EventTreeInspector({
  node, foreshadow, causalEdges, nodes, onReadSource, onSelectRelatedEvent,
}: EventTreeInspectorProps) {
  return (
    <aside aria-label="事件节点详情" className="flex min-h-0 flex-col gap-3 rounded-2xl border border-[#dfc8bd] bg-[#fffaf6] p-4 text-[#503b35] shadow-sm">
      <div className="shrink-0 border-b border-[#ead8ce] pb-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">{node.cause_role === "root" ? "事件起点" : node.cause_role === "main" ? "主链事件" : "次因旁支"}</Badge>
          <Badge variant="outline">第 {node.chapter_order} 章</Badge>
          <Badge variant="outline">{node.evidence_scope === "chapter" ? "章节级依据" : "段落级依据"}</Badge>
        </div>
        <h2 className="mt-3 font-serif text-base font-semibold leading-6">{node.description}</h2>
        {node.cause_role === "secondary" && !node.parent_event_id && <p className="mt-2 text-xs text-[#9b6457]">挂接点待确认，图中未绘制推测连线</p>}
      </div>

      <section className="shrink-0" aria-label="参与实体">
        <h3 className="text-xs font-semibold tracking-wide text-[#946959]">参与实体 · {node.participants.length}</h3>
        {node.participants.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {node.participants.map((participant, index) => (
              <span key={`${participant.entity?.entity_id ?? participant.entity?.name ?? index}-${index}`} className="rounded-lg bg-[#f5eae2] px-2 py-1 text-xs leading-5">
                {participant.entity?.name ?? participant.name ?? "未命名实体"}{participant.role ? ` · ${participant.role}` : ""}
              </span>
            ))}
          </div>
        ) : <p className="mt-1 text-xs text-[#8d766b]">暂无参与实体</p>}
      </section>

      {foreshadow && (
        <section className="shrink-0 border-t border-[#ead8ce] pt-3" aria-label="伏笔状态">
          <h3 className="text-xs font-semibold tracking-wide text-[#946959]">伏笔状态</h3>
          <p className="mt-1 text-xs leading-5">{FORESHADOW_LABELS[foreshadow.status] ?? foreshadow.status} · 第 {foreshadow.first_chapter_id} 至 {foreshadow.last_chapter_id} 章</p>
          {foreshadow.payoff_event_id && nodes.has(foreshadow.payoff_event_id) && (
            <Button variant="ghost" size="sm" className="mt-1 h-7 px-1 text-xs" onClick={() => onSelectRelatedEvent(foreshadow.payoff_event_id!)}>查看回收事件<ArrowRight className="ml-1 h-3 w-3" /></Button>
          )}
        </section>
      )}

      <section aria-label="树间因果联系" className="min-h-0 border-t border-[#ead8ce] pt-3">
        <h3 className="flex items-center gap-1 text-xs font-semibold tracking-wide text-[#946959]"><Link2 className="h-3.5 w-3.5" />树间因果联系</h3>
        {causalEdges.length === 0 ? <p className="mt-1 text-xs text-[#8d766b]">当前任务没有这棵树的树间因果联系</p> : (
          <div className="mt-1 space-y-1.5">
            {causalEdges.map((edge) => {
              const relatedId = nodes.get(edge.source_event_id)?.tree_id === node.tree_id ? edge.target_event_id : edge.source_event_id;
              return <button key={edge.edge_id} type="button" className="block w-full rounded-lg bg-[#f5eae2] px-2 py-1.5 text-left text-xs leading-5 hover:bg-[#eed9ca]" onClick={() => onSelectRelatedEvent(relatedId)}>
                {nodes.get(edge.source_event_id)?.description ?? "未知事件"} → {nodes.get(edge.target_event_id)?.description ?? "未知事件"}
                <span className="block text-[#8d766b]">{edge.is_active ? "当前有效" : "已经失效"}</span>
              </button>;
            })}
          </div>
        )}
      </section>

      <div className="mt-auto shrink-0 border-t border-[#ead8ce] pt-3">
        <p className="mb-2 text-xs leading-5 text-[#8d766b]">{node.evidence_scope === "chapter" ? "依据覆盖整章，不能确定具体发生段落" : "原文中标出精确段落依据"}</p>
        <Button className="w-full" size="sm" onClick={onReadSource}><BookOpen className="mr-2 h-4 w-4" />阅读本章原文</Button>
      </div>
    </aside>
  );
}
