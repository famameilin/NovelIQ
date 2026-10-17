import { useEffect, useMemo, useRef, type RefObject } from "react";
import type { EventTreeListResponse } from "@/api/narrativeTypes";
import { MARKER_RADIUS, type EventTreeLayoutResult } from "./eventTreeLayout";
import { curveCrossesWindow, eventTreeCurves } from "./eventTreeCurves";

export const EVENT_TREE_HIT_SIZE = 28;
const CULL_MARGIN = 320;

import { chartVar } from "./presentation";

interface EventTreeCanvasProps {
  book: EventTreeListResponse;
  layout: EventTreeLayoutResult;
  x: number;
  frameWidth: number;
  selected: string | null;
  /** 选中与已开卡事件始终参与绘制，关系跳转目标不被视口裁剪隐藏 */
  pinnedIds: ReadonlySet<string>;
  onPan: (x: number) => void;
  onSelect: (eventId: string) => void;
  hostRef: RefObject<HTMLDivElement | null>;
}

/** 三段连续空间（上部结果 / 中部大事件与细曲线 / 下部叙事线锚点）共享同一横向位移 */
export function EventTreeCanvas({ book, layout, x, frameWidth, selected, pinnedIds, onPan, onSelect, hostRef }: EventTreeCanvasProps) {
  const drag = useRef<{ startX: number; viewX: number } | null>(null);
  const curves = useMemo(() => eventTreeCurves(book, layout), [book, layout]);
  // 同结果的纵向真实连接会共享路径，按重合数降低背景透明度，保留每项真实关系与选中高亮
  const outcomeOverlap = useMemo(() => {
    const counts = new Map<string, number>();
    for (const curve of curves) if (curve.channel === "outcome") {
      const key = `${curve.targetId}:${layout.positions.get(curve.sourceId)?.x}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [curves, layout]);
  const anchorOrder = useMemo(() => [...layout.arcAnchors.keys()], [layout]);
  const arcColor = useMemo(() => new Map(anchorOrder.map((arcId, index) => [arcId, index])), [anchorOrder]);
  const eventTone = useMemo(() => {
    const tones = new Map<string, string>();
    for (const link of book.event_arc_links) {
      if (!tones.has(link.event_id)) tones.set(link.event_id, chartVar(arcColor.get(link.arc_id) ?? 0));
    }
    return tones;
  }, [book.event_arc_links, arcColor]);

  // 滚轮与触控板（含 Shift 组合）全部接管且不移动画布、不改变尺度
  useEffect(() => {
    const canvas = hostRef.current;
    if (!canvas) return;
    const wheel = (event: WheelEvent) => event.preventDefault();
    canvas.addEventListener("wheel", wheel, { passive: false });
    return () => canvas.removeEventListener("wheel", wheel);
  }, [hostRef]);

  // 视口外绘制裁剪只是渲染优化；选中、开卡事件及其关联端点始终绘制
  const viewLeft = -x - CULL_MARGIN, viewRight = -x + frameWidth + CULL_MARGIN;
  const inWindow = (cx: number) => cx >= viewLeft && cx <= viewRight;
  const visibleEvents = book.events.filter(event => {
    const position = layout.positions.get(event.event_id);
    return position && (inWindow(position.x) || pinnedIds.has(event.event_id));
  });
  const visibleCurves = curves.filter(curve => {
    const sourceX = layout.positions.get(curve.sourceId)?.x ?? layout.arcAnchors.get(curve.sourceId)?.x ?? layout.outcomeBoxes.get(curve.sourceId)?.x;
    const targetX = layout.positions.get(curve.targetId)?.x ?? layout.arcAnchors.get(curve.targetId)?.x ?? layout.outcomeBoxes.get(curve.targetId)?.x;
    const pinned = pinnedIds.has(curve.sourceId) || pinnedIds.has(curve.targetId);
    return pinned || (sourceX != null && targetX != null && curveCrossesWindow(sourceX, targetX, viewLeft, viewRight));
  });
  const visibleOutcomes = book.outcomes.filter(outcome => {
    const box = layout.outcomeBoxes.get(outcome.outcome_id);
    return box && inWindow(box.x);
  });

  return <div
    ref={hostRef}
    aria-label="事件树画布"
    className="relative min-h-0 min-w-0 flex-1 cursor-grab select-none touch-none overflow-hidden active:cursor-grabbing"
    onPointerDown={event => {
      if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
      // 拖拽只横向平移画布；阻止浏览器建立文字选区与原生拖放
      event.preventDefault();
      window.getSelection()?.removeAllRanges();
      drag.current = { startX: event.clientX, viewX: x };
      event.currentTarget.setPointerCapture(event.pointerId);
    }}
    onPointerMove={event => {
      if (!drag.current) return;
      onPan(drag.current.viewX + event.clientX - drag.current.startX);
    }}
    onPointerUp={() => { drag.current = null; }}
    onPointerCancel={() => { drag.current = null; }}
    onLostPointerCapture={() => { drag.current = null; }}
    onDragStart={event => event.preventDefault()}>
    <div className="absolute left-0 top-0" style={{ width: layout.width, height: layout.height, transform: `translateX(${x}px)` }}>
      <svg className="pointer-events-none absolute inset-0 overflow-visible" width={layout.width} height={layout.height} role="img" aria-label="叙事线、结果与大事件之间的关联曲线">
        <desc>细曲线从叙事线锚点扇形汇拢后分流，接入大事件标记边缘端口，再上行连接结果；选中事件的关联路径突出，其余淡显但不隐藏</desc>
        {visibleCurves.map(curve => {
          const tone = curve.channel === "arc" ? chartVar(arcColor.get(curve.sourceId) ?? 0) : curve.channel === "outcome" ? eventTone.get(curve.sourceId) ?? chartVar(0) : chartVar(1);
          const highlight = curve.sourceId === selected || curve.targetId === selected;
          const overlap = curve.channel === "outcome" ? outcomeOverlap.get(`${curve.targetId}:${layout.positions.get(curve.sourceId)?.x}`) ?? 1 : 1;
          return <path
            key={curve.relationIds.join("|")}
            data-source-id={curve.sourceId}
            data-target-id={curve.targetId}
            data-kinds={curve.kinds.join(" ")}
            data-channel={curve.channel}
            data-active={highlight || undefined}
            d={curve.d}
            fill="none"
            style={{ stroke: `hsl(var(${tone}))` }}
            strokeOpacity={highlight ? 0.95 : (selected ? 0.14 : 0.2) / Math.sqrt(overlap)}
            strokeWidth={highlight ? 1.9 : 1.05}
            strokeLinecap="round" />;
        })}
      </svg>
      {visibleOutcomes.map(outcome => {
        const box = layout.outcomeBoxes.get(outcome.outcome_id)!;
        // 上部结果不可点击：标题与说明只参与构图，不作为任何按钮入口
        return <div key={outcome.outcome_id} data-outcome-id={outcome.outcome_id} className="absolute" style={{ left: box.left, top: box.top, width: box.width }}>
          <p className="m-0 truncate text-base font-semibold leading-[22px] text-text" title={outcome.title}>{outcome.title}</p>
          <p className="m-0 line-clamp-2 text-[13px] leading-[18px] text-text-muted" title={outcome.description}>{outcome.description}</p>
        </div>;
      })}
      {visibleEvents.map(event => {
        const position = layout.positions.get(event.event_id)!;
        const tone = eventTone.get(event.event_id) ?? "--chart-neutral";
        const isSelected = selected === event.event_id;
        const left = position.x - EVENT_TREE_HIT_SIZE / 2;
        return <button
          key={event.event_id}
          type="button"
          aria-label={event.title}
          title={event.title}
          data-event-marker={event.event_id}
          data-selected={isSelected || undefined}
          className="group absolute z-10 m-0 border-0 bg-transparent p-0 text-left outline-none"
          style={{ left, top: position.y - EVENT_TREE_HIT_SIZE / 2, width: EVENT_TREE_HIT_SIZE, height: EVENT_TREE_HIT_SIZE }}
          onClick={() => onSelect(event.event_id)}>
          <span
            data-event-hit-target
            className="absolute rounded-full"
            style={{
              left: position.x - EVENT_TREE_HIT_SIZE / 2 - left, top: 0,
              width: EVENT_TREE_HIT_SIZE, height: EVENT_TREE_HIT_SIZE,
            }} />
          <span
            data-event-dot
            className="absolute rounded-full transition-shadow group-focus-visible:ring-2 group-focus-visible:ring-current"
            style={{
              left: position.x - MARKER_RADIUS - left, top: EVENT_TREE_HIT_SIZE / 2 - MARKER_RADIUS,
              width: MARKER_RADIUS * 2, height: MARKER_RADIUS * 2,
              background: `hsl(var(${tone}))`, color: `hsl(var(${tone}))`,
              boxShadow: isSelected ? `0 0 0 4px color-mix(in srgb, hsl(var(${tone})) 22%, transparent), 0 0 0 1.5px hsl(var(--background)), 0 0 18px color-mix(in srgb, hsl(var(${tone})) 55%, transparent)` : `0 0 0 1.5px hsl(var(--background))`,
            }} />
          {isSelected && <span data-event-title className="pointer-events-none absolute left-7 top-1 whitespace-nowrap text-[13px] font-medium leading-5 text-text">{event.title}</span>}
        </button>;
      })}
      {anchorOrder.map(arcId => {
        const anchor = layout.arcAnchors.get(arcId)!;
        const arc = book.arcs.find(item => item.arc_id === arcId);
        if (!arc) return null;
        const tone = chartVar(arcColor.get(arcId) ?? 0);
        return <div key={arcId} data-arc-anchor={arcId} className="absolute flex flex-col items-center" style={{ left: anchor.x - anchor.width / 2, top: anchor.y - 12, width: anchor.width }}>
          <span data-arc-dot className="rounded-full" style={{ width: 24, height: 24, background: `hsl(var(${tone}))`, boxShadow: `0 0 0 6px color-mix(in srgb, hsl(var(${tone})) 16%, transparent), 0 0 0 2px hsl(var(--background))` }} />
          <span className="mt-4 text-center text-base font-bold leading-[22px] text-text">{arc.title}</span>
          <span className="text-center text-[13px] leading-[18px] text-text-muted">{arc.objective}</span>
        </div>;
      })}
    </div>
  </div>;
}

