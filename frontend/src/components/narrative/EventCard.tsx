import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, X } from "lucide-react";
import { getEventTreeNode } from "@/api/results";

import { EVENT_CARD_WIDTH, EVENT_CARD_MAX_HEIGHT, type CardPoint } from "./eventCardPlacement";

interface EventCardProps {
  novelId: string;
  runId: string;
  eventId: string;
  chapters: Array<{ chapter_id: number; title: string }>;
  position: CardPoint;
  zIndex: number;
  frameHeight: number;
  /** 主题色经 CSS 变量引用，卡片不写死色值 */
  toneVar: string;
  onClose: (eventId: string) => void;
  onOpenChild: (parentId: string, childId: string) => void;
  onDrag: (eventId: string, position: CardPoint) => void;
  onOpenReader: (eventId: string) => void;
}

function characterName(item: Record<string, unknown>): string {
  const name = (item as { name?: unknown }).name ?? ((item as { entity?: Record<string, unknown> }).entity?.name);
  return typeof name === "string" && name ? name : "未命名";
}

/** 统一事件卡：大事件与子事件共用同一模板、内容结构与操作 */
export function EventCard({ novelId, runId, eventId, chapters, position, zIndex, frameHeight, toneVar, onClose, onOpenChild, onDrag, onOpenReader }: EventCardProps) {
  const detail = useQuery({ queryKey: ["event-card", novelId, runId, eventId], queryFn: ({ signal }) => getEventTreeNode(novelId, runId, eventId, signal), retry: false, staleTime: 60_000 });
  const drag = useRef<{ pointerId: number; startX: number; startY: number; origin: CardPoint } | null>(null);
  const title = detail.data?.title ?? "事件详情";
  return <section
    role="dialog"
    aria-label={`事件详情：${title}`}
    data-event-card={eventId}
    className="absolute flex flex-col overflow-hidden rounded-md border border-border/40 shadow-xl"
    style={{
      left: position.x, top: position.y, width: EVENT_CARD_WIDTH, maxHeight: Math.min(EVENT_CARD_MAX_HEIGHT, Math.max(88, frameHeight - position.y - 8)), zIndex,
      background: "hsl(var(--event-card-body))", color: "hsl(var(--event-card-body-text))",
    }}
    // 卡片指针与滚轮输入完全隔离，不触发画布平移或页面滚动
    onPointerDown={event => event.stopPropagation()}
    onWheel={event => event.stopPropagation()}
    onDragStart={event => event.preventDefault()}>
    <header
      data-card-header
      className="relative shrink-0 cursor-grab touch-none select-none px-5 py-3 active:cursor-grabbing"
      style={{ background: `linear-gradient(120deg, hsl(var(${toneVar})), color-mix(in srgb, hsl(var(${toneVar})) 60%, hsl(var(--primary))))`, color: "hsl(var(--text-on-primary))" }}
      onPointerDown={event => {
        if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
        // 仅标题区发起卡片拖动，正文阅读、复制与按钮操作不触发
        event.preventDefault();
        window.getSelection()?.removeAllRanges();
        drag.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, origin: position };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={event => {
        if (!drag.current || drag.current.pointerId !== event.pointerId) return;
        onDrag(eventId, { x: drag.current.origin.x + event.clientX - drag.current.startX, y: drag.current.origin.y + event.clientY - drag.current.startY });
      }}
      onPointerUp={() => { drag.current = null; }}
      onPointerCancel={() => { drag.current = null; }}
      onLostPointerCapture={() => { drag.current = null; }}>
      <p className="m-0 text-xs tracking-wide opacity-75">事件</p>
      <h3 className="m-0 mt-0.5 pr-6 text-lg font-bold leading-snug">{title}</h3>
      <button aria-label="关闭事件卡" className="absolute right-2 top-2 rounded p-1.5 outline-none hover:bg-[color-mix(in_srgb,currentColor_15%,transparent)] focus-visible:ring-2 focus-visible:ring-current" onClick={() => onClose(eventId)}><X size={15} /></button>
    </header>
    <div data-card-body className="min-h-0 flex-1 overflow-y-auto px-5 py-3 text-[13px] leading-6">
      {detail.isPending && <p className="opacity-70">正在读取事件…</p>}
      {detail.isError && <p role="alert" className="opacity-90">事件详情读取失败。<button className="underline" onClick={() => void detail.refetch()}>重试</button></p>}
      {detail.data && <>
        <p className="m-0 mb-3 whitespace-pre-wrap">{detail.data.summary || "暂无概要"}</p>
        <hr className="my-2 border-0 border-t" style={{ borderColor: "color-mix(in srgb, currentColor 18%, transparent)" }} />
        <dl className="m-0 grid grid-cols-[76px_1fr] gap-y-1">
          <dt className="opacity-60">章节范围</dt><dd className="m-0">{chapters.find(chapter => chapter.chapter_id === detail.data.from)?.title ?? "未知章节"} 至 {chapters.find(chapter => chapter.chapter_id === detail.data.to)?.title ?? "未知章节"}</dd>
          <dt className="opacity-60">事件类型</dt><dd className="m-0">{detail.data.event_type || "未标注"}</dd>
          <dt className="opacity-60">所属主线</dt><dd className="m-0">{detail.data.arcs.length ? detail.data.arcs.map(arc => arc.title).join(" / ") : "无关联叙事线"}</dd>
          <dt className="opacity-60">涉及人物</dt><dd className="m-0">{detail.data.characters.length ? detail.data.characters.map(characterName).join(" / ") : "未记录"}</dd>
        </dl>
        <hr className="my-2 border-0 border-t" style={{ borderColor: "color-mix(in srgb, currentColor 18%, transparent)" }} />
        <h4 className="m-0 text-[13px] font-normal opacity-60">相关事件</h4>
        {detail.data.direct_children.length ? <ul className="m-0 mt-1 list-none p-0">
          {detail.data.direct_children.map(child => <li key={child.event_id}>
            <button className="block w-full rounded px-1 py-0.5 text-left outline-none hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)] focus-visible:ring-2 focus-visible:ring-current" onClick={() => onOpenChild(eventId, child.event_id)}>
              <span className="mr-2 opacity-50">{child.event_type}</span>{child.title}
            </button>
          </li>)}
        </ul> : <p className="m-0 mt-1 opacity-50">没有直接子事件</p>}
        {detail.data.evidence.length > 0 && <button className="mt-3 flex w-full items-center justify-center gap-2 rounded border py-1.5 text-xs outline-none hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)] focus-visible:ring-2 focus-visible:ring-current" style={{ borderColor: "color-mix(in srgb, currentColor 28%, transparent)" }} onClick={() => onOpenReader(eventId)}><BookOpen size={14} />阅读原文</button>}
      </>}
    </div>
  </section>;
}
