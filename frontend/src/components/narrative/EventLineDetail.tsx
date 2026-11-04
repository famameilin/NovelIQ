import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, X } from "lucide-react";
import { getEventTreeNode } from "@/api/results";
import type { EventTreeListResponse } from "@/api/narrativeTypes";
import type { EventLineBook } from "./eventLines";
import { eventLineColor } from "./presentation";

interface EventLineDetailProps {
  novelId: string;
  taskId: string;
  runId: string;
  book: EventTreeListResponse;
  lineBook: EventLineBook;
  bookTitle: string;
  selected: string | null;
  selectedLine?: string | null;
  onSelect: (eventId: string, lineId?: string) => void;
  onClose: () => void;
  onOpenReader: (eventId: string) => void;
}

const overline = "m-0 text-[10.5px] font-semibold uppercase tracking-[1.4px] text-text-muted";
const rowLabel = "m-0 text-[11.5px] text-text-muted";
const rowValue = "m-0 text-[12.5px] text-text";

/** 右侧详情：选中事件树节点时列出其所属事件，选中事件时展示概括与关联 */
export function EventLineDetail({ novelId, taskId, runId, book, lineBook, bookTitle, selected, selectedLine, onSelect, onClose, onOpenReader }: EventLineDetailProps) {
  const event = selected ? book.events.find(item => item.event_id === selected) : undefined;
  const line = selected ? lineBook.lineByEvent.get(selected)?.find(item => item.id === selectedLine)
    ?? lineBook.lineByEvent.get(selected)?.[0] : undefined;
  const nodeEntry = useMemo(() => {
    if (!selected) return undefined;
    for (const item of lineBook.lines) {
      const node = item.nodes.find(candidate => candidate.eventId === selected && !candidate.focusOnly);
      if (node) return { line: item, node };
    }
    return undefined;
  }, [lineBook.lines, selected]);
  const detail = useQuery({
    queryKey: ["event-line-card", novelId, runId, selected],
    queryFn: ({ signal }) => getEventTreeNode(novelId, taskId, selected!, signal),
    enabled: !!selected && !nodeEntry,
    retry: false,
    staleTime: 60_000,
  });
  const eventTitles = useMemo(() => new Map(book.events.map(item => [item.event_id, item.title])), [book.events]);
  const chapterTitles = useMemo(() => new Map(book.chapters.map(chapter => [chapter.chapter_id, chapter.title])), [book.chapters]);
  const from = event ? chapterTitles.get(event.from) ?? `第 ${event.from} 章` : "";
  const to = event ? chapterTitles.get(event.to) ?? `第 ${event.to} 章` : "";
  const owned = useMemo(() => {
    if (!nodeEntry) return [];
    const byId = new Map(book.events.map(item => [item.event_id, item]));
    return nodeEntry.node.eventIds.flatMap(id => { const item = byId.get(id); return item ? [item] : []; });
  }, [book.events, nodeEntry]);
  const related = useMemo(() => {
    if (!selected || !detail.data || nodeEntry) return [];
    const seen = new Set<string>([selected]);
    const rows: Array<{ id: string; title: string }> = [];
    for (const child of [...detail.data.direct_parents, ...detail.data.direct_children]) {
      if (seen.has(child.event_id)) continue;
      seen.add(child.event_id);
      rows.push({ id: child.event_id, title: child.title });
    }
    for (const relation of detail.data.relations) {
      const id = relation.source_id === selected ? relation.target_id : relation.source_id;
      if (seen.has(id)) continue;
      seen.add(id);
      rows.push({ id, title: eventTitles.get(id) ?? id });
    }
    return rows;
  }, [detail.data, eventTitles, nodeEntry, selected]);
  const tone = line ? eventLineColor(line.id, line.colorIndex) : "hsl(var(--text-muted))";
  const lineEntry = !!event?.is_event_line;

  const rowLine = (id: string) => lineBook.lineByEvent.get(id)?.find(item => item.id === line?.id) ?? lineBook.lineByEvent.get(id)?.[0];

  return <aside className="flex h-full w-[332px] shrink-0 flex-col border-l border-border bg-surface" aria-label="事件详情">
    <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-border/70 px-5">
      <h2 className="m-0 text-[13px] font-semibold text-text">事件详情</h2>
      <button type="button" aria-label="关闭详情" className="rounded p-1 text-text-muted outline-none hover:bg-surface-hover hover:text-text focus-visible:ring-2 focus-visible:ring-primary/40" onClick={onClose}><X size={17} /></button>
    </header>
    {!selected || !event ? <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
      <div>
        <p className={overline}>当前全书</p>
        <p className="m-0 mt-1.5 font-serif text-[21px] leading-7 text-text">{bookTitle}</p>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        <div className="rounded-md border border-border/70 px-3 py-2.5"><p className={rowLabel}>叙事线</p><p className="m-0 mt-1 text-[17px] font-semibold text-text">{lineBook.lines.length}</p></div>
        <div className="rounded-md border border-border/70 px-3 py-2.5"><p className={rowLabel}>事件树节点</p><p className="m-0 mt-1 text-[17px] font-semibold text-text">{lineBook.lines.reduce((total, item) => total + item.nodes.length, 0)}</p></div>
      </div>
      <p className="m-0 text-[12.5px] leading-5 text-text-muted">画布只展示事件树节点。点击任一节点，这里会列出该节点所属的全部事件。</p>
      <div>
        <p className={overline}>叙事线</p>
        <ul className="m-0 mt-2 flex list-none flex-col gap-0.5 p-0">
          {lineBook.lines.map(item => <li key={item.id}>
            <button type="button" className="flex w-full items-center gap-2 rounded px-1.5 py-1.5 text-left text-[12.5px] text-text outline-none hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-primary/40" onClick={() => { const node = item.nodes[0]; if (node) onSelect(node.eventId, item.id); }}>
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: eventLineColor(item.id, item.colorIndex) }} />
              <span className="min-w-0 flex-1 truncate">{item.title}</span>
              <span className="text-[11px] text-text-muted">{item.nodes.length} 个节点</span>
            </button>
          </li>)}
        </ul>
      </div>
    </div> : <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        <p className={overline}>{nodeEntry ? "事件树节点" : "当前事件"}</p>
        <h3 className="m-0 mt-1.5 font-serif text-[21px] font-normal leading-7 text-text">{event.title}</h3>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10.5px] font-medium ${nodeEntry ? (lineEntry ? "bg-[#fde8ec] text-[#d9485f]" : "bg-primary/10 text-primary") : "bg-surface-hover text-text-muted"}`}>
            {nodeEntry ? (nodeEntry.node.isRoot ? "事件线入口" : "关键节点") : "事件"}
          </span>
          {event.event_type && <span className="shrink-0 rounded-full bg-surface-hover px-2.5 py-1 text-[10.5px] text-text-muted">{event.event_type}</span>}
          <span className="shrink-0 text-[11px] text-text-muted">第 {event.chapter_order} 章</span>
        </div>
        <p className="m-0 mt-4 whitespace-pre-wrap text-[12.5px] leading-6 text-text-muted">{event.summary || event.problem || "暂无概要"}</p>

        <div className="mt-5">
          <p className={overline}>结构信息</p>
          <dl className="m-0 mt-2 grid grid-cols-[76px_1fr] gap-x-2 gap-y-2">
            <dt className={rowLabel}>所在叙事线</dt>
            <dd className="m-0 flex min-w-0 items-center gap-1.5">
              {line && <span className="inline-flex min-w-0 items-center gap-1.5 text-[12.5px] font-medium" style={{ color: tone }}>
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: tone }} />
                <span className="truncate">{line.title}</span>
              </span>}
            </dd>
            {nodeEntry ? <>
              <dt className={rowLabel}>所属事件</dt>
              <dd className={rowValue}>{owned.length} 个</dd>
              <dt className={rowLabel}>直接分支</dt>
              <dd className={rowValue}>{nodeEntry.node.childCount} 个</dd>
            </> : <>
              <dt className={rowLabel}>章节范围</dt>
              <dd className={rowValue}>{from === to ? from : `${from} 至 ${to}`}</dd>
              <dt className={rowLabel}>直接关联</dt>
              <dd className={rowValue}>{related.length} 个</dd>
            </>}
          </dl>
        </div>

        {nodeEntry ? <div className="mt-5 border-t border-border/70 pt-4">
          <div className="flex items-baseline justify-between">
            <p className={overline}>所属事件（{owned.length}）</p>
            <span className="text-[10.5px] text-text-muted">点击查看事件</span>
          </div>
          <ul className="m-0 mt-1.5 flex list-none flex-col p-0">
            {owned.map(item => {
              const ownerLine = rowLine(item.event_id);
              return <li key={item.event_id} className="border-b border-border/50 last:border-0">
                <button type="button" className="flex w-full items-center gap-2 py-2 text-left text-[12.5px] text-text outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-primary/40" onClick={() => onSelect(item.event_id, ownerLine?.id)}>
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: ownerLine ? eventLineColor(ownerLine.id, ownerLine.colorIndex) : "hsl(var(--text-muted))" }} />
                  <span className="min-w-0 flex-1 truncate">{item.title}</span>
                  <span className="shrink-0 text-[10.5px] text-text-muted">第 {item.chapter_order} 章</span>
                  <ChevronRight size={14} className="shrink-0 text-text-muted" />
                </button>
              </li>;
            })}
          </ul>
        </div> : <div className="mt-5 border-t border-border/70 pt-4">
          <div className="flex items-center justify-between">
            <p className={overline}>相关事件（{related.length}）</p>
            {detail.isPending && <span className="text-[10.5px] text-text-muted">读取中…</span>}
          </div>
          {detail.isError && <p role="alert" className="m-0 mt-2 text-[12px] text-destructive">关联事件读取失败。<button type="button" className="underline" onClick={() => void detail.refetch()}>重试</button></p>}
          {related.length > 0 ? <ul className="m-0 mt-1.5 flex list-none flex-col p-0">{related.map(row => {
            const itemLine = rowLine(row.id);
            return <li key={row.id} className="border-b border-border/50 last:border-0">
              <button type="button" className="flex w-full items-center gap-2 py-2 text-left text-[12.5px] text-text outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-primary/40" onClick={() => onSelect(row.id, itemLine?.id)}>
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: itemLine ? eventLineColor(itemLine.id, itemLine.colorIndex) : "hsl(var(--text-muted))" }} />
                <span className="min-w-0 flex-1 truncate">{row.title}</span>
                <ChevronRight size={14} className="shrink-0 text-text-muted" />
              </button>
            </li>;
          })}</ul> : !detail.isPending && <p className="m-0 mt-2 text-[11.5px] text-text-muted">没有直接关联事件。</p>}
        </div>}
      </div>
      <div className="shrink-0 border-t border-border/70 px-5 py-3.5">
        <button type="button" className="flex w-full items-center justify-center gap-1.5 rounded-md bg-[#1f2a44] px-4 py-2 text-[12.5px] font-medium text-white outline-none hover:bg-[#2a3856] focus-visible:ring-2 focus-visible:ring-primary/50" onClick={() => onOpenReader(selected)}>
          查看完整内容
        </button>
      </div>
    </div>}
  </aside>;
}
