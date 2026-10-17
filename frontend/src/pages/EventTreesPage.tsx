import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { List, RotateCcw, X } from "lucide-react";
import { getEventTreeBook, getEventTreeNode } from "@/api/results";
import type { EventRelationItem, EventTreeListResponse } from "@/api/narrativeTypes";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { NarrativeError, NarrativeReader } from "@/components/narrative/NarrativePanels";
import { EventTreeCanvas } from "@/components/narrative/EventTreeCanvas";
import { EventCard } from "@/components/narrative/EventCard";
import { placeChildCard, placeRootCard, EVENT_CARD_WIDTH, type CardPoint } from "@/components/narrative/eventCardPlacement";
import { eventTreeLayout } from "@/components/narrative/eventTreeLayout";
import { clampX, locateX } from "@/components/narrative/treeViewport";
import { chartVar, control, narrativeHeader, narrativeLine, narrativePaper } from "@/components/narrative/presentation";
import { useNarrativeSize } from "@/components/narrative/useNarrativeSize";
import { useNarrativeState } from "@/components/narrative/useNarrativeState";
import { shouldWriteBackTaskUrl, useNovelScopedTask } from "@/hooks/useNovelScopedTask";

interface TreeState { selected: string | null; x: number; cards: Array<{ eventId: string; position: CardPoint }>; reader: string | null }
export function EventTreesPage() {
  const { novelId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const urlTask = params.get("task_id");
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTask);
  const task = urlTask ?? storeTaskId;
  useEffect(() => {
    if (novelId && shouldWriteBackTaskUrl(urlTask, storeTaskId, urlTaskSyncRef)) navigate(`/novels/${novelId}/event-trees?task_id=${storeTaskId}`, { replace: true });
  }, [navigate, novelId, storeTaskId, urlTask, urlTaskSyncRef]);
  const book = useQuery({ queryKey: ["event-trees-book", novelId, task], queryFn: ({ signal }) => getEventTreeBook(novelId!, task!, signal), enabled: !!novelId && !!task, retry: false, staleTime: 0 });
  return <AnalysisWorkspace title="事件树" headerClassName={`${narrativeHeader} py-3`} contentClassName="py-0" className={`${narrativePaper} min-w-[860px] px-7 pb-2 pt-0`}>
    {!task && <p>请先选择分析任务</p>}
    {task && book.isPending && <p className="p-6 text-sm text-text-muted">正在读取全书事件树…</p>}
    {book.isError && <NarrativeError error={book.error} retry={() => void book.refetch()} />}
    {book.data?.organization_status === "pending_diagnosis" && <p className="p-6 text-sm text-text-muted">事件声明已保存，等待诊断确认全书事件树</p>}
    {book.data && book.data.organization_status !== "pending_diagnosis" && novelId && <TreeWorkspace key={`${novelId}:${book.data.run_id}`} novelId={novelId} book={book.data} targetEvent={params.get("event_id")} />}
  </AnalysisWorkspace>;
}
function TreeWorkspace({ novelId, book, targetEvent }: { novelId: string; book: EventTreeListResponse; targetEvent: string | null }) {
  const [host, size] = useNarrativeSize();
  // 新契约独立状态键，不恢复已取消的搜索和缩放状态
  const [view, update] = useNarrativeState<TreeState>(`${novelId}:${book.run_id}:event-trees:${book.contract_version}`, { selected: null, x: 0, cards: [], reader: null });
  const [directory, setDirectory] = useState(false);
  const layout = useMemo(() => eventTreeLayout(book, size.width, size.height), [book, size]);
  const x = clampX(view.x, size.width, layout.width);
  const pinned = useMemo(() => new Set([...(view.selected ? [view.selected] : []), ...view.cards.map(card => card.eventId)]), [view.selected, view.cards]);
  const reader = useQuery({ queryKey: ["event-card", novelId, book.run_id, view.reader], queryFn: ({ signal }) => getEventTreeNode(novelId, book.run_id, view.reader!, signal), enabled: !!view.reader, retry: false });
  const selectedDetail = useQuery({ queryKey: ["event-card", novelId, book.run_id, view.selected], queryFn: ({ signal }) => getEventTreeNode(novelId, book.run_id, view.selected!, signal), enabled: !!view.selected, retry: false });
  const target = useQuery({ queryKey: ["event-card", novelId, book.run_id, targetEvent], queryFn: ({ signal }) => getEventTreeNode(novelId, book.run_id, targetEvent!, signal), enabled: !!targetEvent, retry: false });
  // 深链沿正式包含路径恢复多张事件卡，不创建子事件画布入口
  useEffect(() => {
    const path = target.data ? [...target.data.ancestry, target.data.event_id] : [];
    if (!path.length) return;
    const topPosition = layout.positions.get(path[0]);
    update(previous => {
      const cards = [...previous.cards];
      for (const [index, eventId] of path.entries()) {
        if (cards.some(card => card.eventId === eventId)) continue;
        const parent = cards.find(card => card.eventId === path[index - 1]);
        cards.push({ eventId, position: parent ? placeChildCard(parent.position, size.width, cards.map(card => card.position), size.height) : placeRootCard(cards.length, size.width, topPosition ? { x: topPosition.x + locateX(size.width, layout.width, topPosition.x), y: topPosition.y } : undefined, size.height) });
      }
      return { cards, selected: path[0], ...(topPosition ? { x: locateX(size.width, layout.width, topPosition.x) } : {}) };
    });
  }, [target.data, layout, size.width, size.height, update]);
  function open(eventId: string, parentId?: string) {
    const position = layout.positions.get(eventId);
    update(previous => {
      const parent = previous.cards.find(card => card.eventId === parentId);
      const existing = previous.cards.find(card => card.eventId === eventId);
      const card = existing ?? { eventId, position: parent ? placeChildCard(parent.position, size.width, previous.cards.map(card => card.position), size.height) : placeRootCard(previous.cards.length, size.width, position ? { x: position.x + locateX(size.width, layout.width, position.x), y: position.y } : undefined, size.height) };
      return { selected: position ? eventId : previous.selected, cards: [...previous.cards.filter(item => item.eventId !== eventId), card], reader: null, ...(position && !parentId ? { x: locateX(size.width, layout.width, position.x) } : {}) };
    });
    setDirectory(false);
  }
  function drag(id: string, point: CardPoint) {
    update(previous => ({ cards: previous.cards.map(item => item.eventId === id ? { ...item, position: { x: Math.max(8, Math.min(point.x, size.width - EVENT_CARD_WIDTH - 8)), y: Math.max(8, Math.min(point.y, size.height - 64)) } } : item) }));
  }
  function follow(relation: EventRelationItem) {
    const locator = relation.locator;
    if (!locator) return;
    const destination = locator.target_id;
    if (destination) {
      const path = [...locator.ancestor_event_ids, destination].filter((id, index, ids) => ids.indexOf(id) === index);
      path.forEach((id, index) => open(id, path[index - 1]));
    }

  }
  return <section className="flex h-full min-h-0 flex-1 flex-col overflow-hidden" aria-label="全书事件树">
    <div className={`flex shrink-0 items-center justify-between border-b py-3 ${narrativeLine}`}>
      <p className="text-xs text-text-muted">全书 · {book.counts.top_level_events} 个大事件 · {book.counts.child_events} 个子事件 · {book.counts.outcomes} 个结果 · {book.counts.arcs} 条叙事线</p>
      <div className="flex gap-2"><button className={control} onClick={() => setDirectory(!directory)}><List size={15} />结构目录</button><button className={control} aria-label="复位画布" onClick={() => update({ x: 0 })}><RotateCcw size={15} /></button></div>
    </div>
    <div className="relative flex min-h-0 flex-1 overflow-hidden">
      <EventTreeCanvas book={book} layout={layout} x={x} frameWidth={size.width} selected={view.selected} pinnedIds={pinned} onPan={value => update({ x: clampX(value, size.width, layout.width) })} onSelect={id => open(id)} hostRef={host} />
      {directory && <aside className="absolute bottom-3 left-3 top-3 z-40 flex w-72 flex-col overflow-hidden rounded border border-border bg-surface shadow-xl" aria-label="结构目录"><header className="flex items-center justify-between p-3">结构目录<button aria-label="关闭目录" onClick={() => setDirectory(false)}><X size={16} /></button></header><div className="min-h-0 overflow-y-auto p-3">{book.events.map(event => <button key={event.event_id} className="block w-full py-2 text-left text-sm hover:text-primary" onClick={() => open(event.event_id)}>{event.title}</button>)}{selectedDetail.data?.relations.some(relation => relation.locator) && <><p className="mt-4 border-t border-border pt-3 text-xs text-text-muted">{selectedDetail.data.title}的真实关系</p>{selectedDetail.data.relations.filter(relation => relation.locator).map((relation, index) => <button key={relation.relation_id ?? index} className="block w-full py-2 text-left text-sm hover:text-primary" onClick={() => follow(relation)}><span className="mr-2 text-text-muted">{relation.relation_type}</span>{relation.locator!.title}</button>)}</>}</div></aside>}
      {view.cards.map((card, index) => <EventCard key={card.eventId} novelId={novelId} runId={book.run_id} eventId={card.eventId} position={card.position} frameHeight={size.height} zIndex={30 + index} toneVar={chartVar(Math.max(0, book.arcs.findIndex(arc => book.event_arc_links.some(link => link.event_id === card.eventId && link.arc_id === arc.arc_id))))} onClose={id => update(previous => ({ cards: previous.cards.filter(item => item.eventId !== id), reader: previous.reader === id ? null : previous.reader }))} onOpenChild={(parent, child) => open(child, parent)} onDrag={drag} onOpenReader={id => update({ reader: id })} />)}
    </div>
    {view.reader && reader.isError && <NarrativeError error={reader.error} retry={() => void reader.refetch()} />}
    {target.isError && <NarrativeError error={target.error} retry={() => void target.refetch()} />}
    {view.reader && reader.data && <NarrativeReader key={view.reader} novelId={novelId} runId={book.run_id} page="event-trees" location={{ id: view.reader, kind: "event", evidence_scope: reader.data.evidence_scope, anchor_paragraph_ids: reader.data.evidence.filter(item => item.paragraph_id != null).map(item => Number(item.paragraph_id)).filter(Number.isFinite), evidence: reader.data.evidence }} onClose={() => update({ reader: null })} />}
  </section>;
}
