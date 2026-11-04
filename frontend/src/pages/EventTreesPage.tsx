import { eventDisplayKey } from "@/api/eventQueues";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Maximize2, Minimize2, Minus, Plus, RotateCcw, Search } from "lucide-react";
import { getNovel } from "@/api/novels";
import { getEventTreeBook, getNarrativeSource } from "@/api/results";
import type { EventTreeListResponse } from "@/api/narrativeTypes";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { NarrativeError, NarrativeReader } from "@/components/narrative/NarrativePanels";
import { EventLinesCanvas } from "@/components/narrative/EventLinesCanvas";
import { EventLineDetail } from "@/components/narrative/EventLineDetail";
import { buildEventLines, type EventLine } from "@/components/narrative/eventLines";
import { eventLineLayout, EVENT_LINE_MIN_WIDTH } from "@/components/narrative/eventLineLayout";
import { eventLineColor, narrativePaper } from "@/components/narrative/presentation";
import { useNarrativeSize } from "@/components/narrative/useNarrativeSize";
import { clampViewport, locateViewport, zoomAround } from "@/components/narrative/treeViewport";
import { shouldWriteBackTaskUrl, useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { useNovelTitle } from "@/hooks/useNovelTitle";

const toolbarControl = "inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-xs text-text-muted outline-none hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-primary/40";

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
  const book = useQuery({
    queryKey: ["event-trees-book", novelId, task],
    queryFn: async ({ signal }) => {
      // 在发起大体积查询前检查挂载期间的取消状态
      await Promise.resolve();
      signal.throwIfAborted();
      return getEventTreeBook(novelId!, task!, signal);
    },
    enabled: !!novelId && !!task,
    retry: false,
    staleTime: 0,
  });
  const title = useNovelTitle("事件树");
  return <AnalysisWorkspace title={title} headerClassName="px-8 2xl:px-10" contentClassName="py-0" className={`${narrativePaper} min-w-[860px] max-w-full px-0 pb-[30px] 2xl:px-0`}>
    {!task && <p>请先选择分析任务</p>}
    {task && book.isPending && <p className="p-6 text-sm text-text-muted">正在读取全书事件树…</p>}
    {book.isError && <NarrativeError error={book.error} retry={() => void book.refetch()} />}
    {book.data && novelId && task && <EventLinesWorkspace key={`${novelId}:${book.data.run_id}`} novelId={novelId} taskId={task} book={book.data} targetEvent={params.get("event_id")} />}
  </AnalysisWorkspace>;
}

function EventLinesWorkspace({ novelId, taskId, book, targetEvent }: { novelId: string; taskId: string; book: EventTreeListResponse; targetEvent: string | null }) {
  const [host, size] = useNarrativeSize();
  const [selected, setSelected] = useState<string | null>(targetEvent);
  const [detailOpen, setDetailOpen] = useState(true);
  const [selectedLine, setSelectedLine] = useState<string | null>(null);
  const [reader, setReader] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showRelations, setShowRelations] = useState(true);
  const [viewMode, setViewMode] = useState<"lines" | "directory">("lines");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [fullscreen, setFullscreen] = useState(false);
  const autoSelected = useRef(false);
  const locatedTarget = useRef<string | null>(null);
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const novel = useQuery({ queryKey: ["novel", novelId], queryFn: () => getNovel(novelId), enabled: !!novelId, staleTime: 60_000 });
  const lineBook = useMemo(() => buildEventLines(book, targetEvent ?? undefined), [book, targetEvent]);
  const layout = useMemo(() => eventLineLayout(lineBook, Math.max(size.width, EVENT_LINE_MIN_WIDTH), size.height), [lineBook, size.width, size.height]);
  const frame = { width: size.width, height: size.height };
  const content = { width: layout.width * zoom, height: layout.height * zoom };
  const view = clampViewport(pan, frame, content);
  const bookTitle = novel.data?.title ?? "全书";
  const readerQuery = useQuery({ queryKey: ["event-reader-source", novelId, book.run_id, reader], queryFn: async ({ signal }) => {
    const source = await getNarrativeSource(novelId, taskId, { page: "event-trees", id: reader!, kind: "event" }, signal);
    if (!source.evidence || !source.evidence_scope) throw new Error("原文缺少事件证据");
    return { ...source, evidence: source.evidence, evidence_scope: source.evidence_scope };
  }, enabled: !!reader, retry: false });
  useEffect(() => {
    const onChange = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  useEffect(() => {
    if (autoSelected.current || targetEvent || !lineBook.lines.length) return;
    autoSelected.current = true;
    const firstLine = lineBook.lines[0];
    const nodeIds = new Set(firstLine.nodes.filter(node => !node.isRoot).map(node => node.eventId));
    const candidates = firstLine.events.filter(event => nodeIds.has(event.event_id));
    const pick = [...candidates].sort((a, b) => b.summary.length - a.summary.length)[0] ?? firstLine.events[0];
    if (pick) {
      setSelected(pick.event_id);
      setSelectedLine(firstLine.id);
    }
  }, [lineBook.lines, targetEvent]);
  useEffect(() => {
    if (!targetEvent || locatedTarget.current === targetEvent || !lineBook.lineByEvent.has(targetEvent) || !size.width) return;
    locatedTarget.current = targetEvent;
    setSelected(targetEvent);
    setSelectedLine(lineBook.lineByEvent.get(targetEvent)![0].id);
    const placed = layout.pointByEvent.get(eventDisplayKey(lineBook.lineByEvent.get(targetEvent)![0].id, targetEvent));
    if (placed) setPan(locateViewport({ x: placed.x, y: placed.y }, frame, { width: layout.width, height: layout.height }, zoomRef.current));
  }, [targetEvent, lineBook, layout, frame.width, frame.height]);

  function select(eventId: string, lineId?: string) {
    setDetailOpen(true);
    setSelected(eventId);
    const candidates = lineBook.lineByEvent.get(eventId);
    const line = candidates?.find(item => item.id === lineId)?.id
      ?? candidates?.find(item => item.id === selectedLine)?.id ?? candidates?.[0]?.id;
    setSelectedLine(line ?? null);
    const placed = line ? layout.pointByEvent.get(eventDisplayKey(line, eventId)) : undefined;
    if (placed) setPan(locateViewport({ x: placed.x, y: placed.y }, frame, { width: layout.width, height: layout.height }, zoom));
  }
  function changeZoom(delta: number) {
    const next = Math.round(Math.min(1.5, Math.max(0.3, zoom + delta)) * 100) / 100;
    if (next === zoom) return;
    setPan(previous => ({
      x: zoomAround(previous.x, frame.width, layout.width, zoom, next),
      y: zoomAround(previous.y, frame.height, layout.height, zoom, next),
    }));
    setZoom(next);
  }
  function resetView() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }
  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch {
      setFullscreen(false);
    }
  }
  const directoryLine = (line: EventLine) => line.events;

  return <section className="flex min-h-0 flex-1 flex-col" aria-label="全书事件树">
    <div className="flex min-h-0 flex-1 overflow-hidden rounded-[10px] border border-border bg-surface shadow-[0_1px_2px_rgba(32,36,39,0.05)]">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border/70 px-5 py-2.5">
          <div className="flex min-w-0 items-baseline gap-3">
            <h2 className="m-0 shrink-0 text-[15px] font-bold leading-5 text-text">事件关系图</h2>
            <span className="truncate text-[11.5px] text-text-muted">{viewMode === "lines" ? "叙事线总览 · 只展示事件树节点，点击查看所属事件" : "事件目录 · 按叙事线逐条列出全部事件"}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative w-[200px]">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
              <input aria-label="搜索事件" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索事件…" className="h-8 w-full rounded-md border border-border bg-surface pl-9 pr-3 text-[13px] text-text outline-none placeholder:text-text-muted/70 focus-visible:ring-2 focus-visible:ring-primary/40" />
            </label>
            <select aria-label="视图样式" className={toolbarControl} value={viewMode} onChange={event => setViewMode(event.target.value as "lines" | "directory")}>
              <option value="lines">事件线</option>
              <option value="directory">目录</option>
            </select>
            <button type="button" aria-label={fullscreen ? "退出全屏" : "全屏"} className="grid h-8 w-8 place-items-center rounded-md border border-border bg-surface text-text-muted outline-none hover:bg-surface-hover hover:text-text focus-visible:ring-2 focus-visible:ring-primary/40" onClick={() => void toggleFullscreen()}>
              {fullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
          </div>
        </header>
        <div className="relative flex min-h-0 flex-1 flex-col">
        {viewMode === "lines" ? <EventLinesCanvas
          book={book}
          layout={layout}
          bookTitle={bookTitle}
          x={view.x}
          y={view.y}
          frameWidth={size.width}
          selected={selected}
          selectedLine={selectedLine}
          query={query}
          showRelations={showRelations}
          zoom={zoom}
          onSelect={select}
          onPan={(x, y) => setPan(clampViewport({ x, y }, frame, content))}
          hostRef={host}
        /> : <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4 pt-5" aria-label="事件目录">
          {lineBook.lines.map(line => <section key={line.id} className="mb-6">
            <header className="flex items-center gap-2 border-b border-border pb-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: eventLineColor(line.id, line.colorIndex) }} />
              <h3 className="m-0 text-[15px] font-medium text-text">{line.title}</h3>
              <span className="text-[11px] text-text-muted">{line.eventCount} 个事件 · {line.objective}</span>
            </header>
            <div className="mt-2 grid grid-cols-2 gap-x-8">
              {directoryLine(line).map(event => <button key={event.event_id} type="button" className="flex min-w-0 items-center gap-2 border-b border-border/50 py-1.5 text-left text-[13px] text-text-muted outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-primary/40" onClick={() => select(event.event_id, line.id)}>
                <span className="min-w-0 flex-1 truncate">{event.title}</span>
                <span className="shrink-0 text-[11px]">第 {event.chapter_order} 章</span>
              </button>)}
            </div>
          </section>)}
        </div>}
        </div>
        <footer className="flex h-[52px] shrink-0 items-center justify-between gap-4 border-t border-border/70 px-5">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11.5px] text-text-muted">
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full border-[1.5px] border-primary bg-surface" />事件树节点 · 大小表示所属事件数量</span>
            <button type="button" role="switch" aria-checked={showRelations} onClick={() => setShowRelations(value => !value)} className="flex items-center gap-2 text-[11.5px] text-text-muted outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
              <span className="h-px w-5 border-t border-dashed border-text-muted" />
              <span className={`relative h-4 w-7 rounded-full transition-colors ${showRelations ? "bg-primary" : "bg-border"}`}>
                <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-surface shadow-sm transition-all ${showRelations ? "left-3.5" : "left-0.5"}`} />
              </span>
              显示关联线
            </button>
          </div>
          <div className="flex items-center gap-1">
            <button type="button" aria-label="缩小" className="grid h-7 w-7 place-items-center rounded text-text-muted outline-none hover:bg-surface-hover hover:text-text focus-visible:ring-2 focus-visible:ring-primary/40" onClick={() => changeZoom(-0.1)}><Minus size={14} /></button>
            <span className="w-12 text-center text-[12px] tabular-nums text-text">{Math.round(zoom * 100)}%</span>
            <button type="button" aria-label="放大" className="grid h-7 w-7 place-items-center rounded text-text-muted outline-none hover:bg-surface-hover hover:text-text focus-visible:ring-2 focus-visible:ring-primary/40" onClick={() => changeZoom(0.1)}><Plus size={14} /></button>
            <button type="button" aria-label="适应画布" className="ml-1 grid h-7 w-7 place-items-center rounded text-text-muted outline-none hover:bg-surface-hover hover:text-text focus-visible:ring-2 focus-visible:ring-primary/40" onClick={resetView}><RotateCcw size={14} /></button>
          </div>
        </footer>
      </div>
      {detailOpen && <EventLineDetail novelId={novelId} taskId={taskId} runId={book.run_id} book={book} lineBook={lineBook} bookTitle={bookTitle} selected={selected} selectedLine={selectedLine} onSelect={select} onClose={() => { setDetailOpen(false); setSelected(null); }} onOpenReader={setReader} />}
    </div>
    {reader && readerQuery.isError && <NarrativeReader key={`${reader}:error`} novelId={novelId} taskId={taskId} runId={book.run_id} page="event-trees" location={{ id: reader, kind: "event", evidence_scope: "chapter", anchor_paragraph_ids: [], evidence: [] }} initialError={{ error: readerQuery.error, retry: () => void readerQuery.refetch() }} onClose={() => setReader(null)} />}
    {reader && readerQuery.data && <NarrativeReader key={reader} novelId={novelId} taskId={taskId} runId={book.run_id} page="event-trees" initialSource={readerQuery.data} location={{ id: reader, kind: "event", chapter_id: readerQuery.data.chapter_id, evidence_scope: readerQuery.data.evidence_scope, anchor_paragraph_ids: readerQuery.data.evidence.filter(item => item.paragraph_id != null).map(item => Number(item.paragraph_id)).filter(Number.isFinite), evidence: readerQuery.data.evidence }} onClose={() => setReader(null)} />}
  </section>;
}
