import { eventDisplayKey } from "@/api/eventQueues";
import { useMemo, useRef, type RefObject } from "react";
import type { EventTreeListResponse } from "@/api/narrativeTypes";
import type { EventLineLayoutResult } from "./eventLineLayout";
import { eventLineColor } from "./presentation";

interface EventLinesCanvasProps {
  book: EventTreeListResponse;
  layout: EventLineLayoutResult;
  bookTitle: string;
  x: number;
  y: number;
  frameWidth: number;
  selected: string | null;
  selectedLine?: string | null;
  query: string;
  showRelations: boolean;
  zoom: number;
  onSelect: (eventId: string, lineId?: string) => void;
  onPan: (x: number, y: number) => void;
  hostRef: RefObject<HTMLDivElement | null>;
}

/** 叙事线导轨画布：左侧线名与事件数，右侧按顺序排开事件树节点，点击节点查看所属事件 */
export function EventLinesCanvas({ book, layout, bookTitle, x, y, frameWidth, selected, selectedLine, query, showRelations, zoom, onSelect, onPan, hostRef }: EventLinesCanvasProps) {
  const drag = useRef<{ startX: number; startY: number; viewX: number; viewY: number } | null>(null);
  const terms = query.trim().toLowerCase();
  const eventTitles = useMemo(() => new Map(book.events.map(event => [event.event_id, event.title])), [book.events]);
  const matches = useMemo(() => {
    if (!terms) return null;
    const ids = new Set<string>();
    for (const placed of layout.lines) {
      for (const node of placed.nodes) {
        const own = `${node.node.title} ${node.node.displayTitle}`.toLowerCase().includes(terms);
        const inside = node.node.eventIds.some(id => (eventTitles.get(id) ?? "").toLowerCase().includes(terms));
        if (own || inside) ids.add(eventDisplayKey(placed.line.id, node.node.eventId));
      }
    }
    return ids;
  }, [eventTitles, layout.lines, terms]);
  const lineMatches = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const placed of layout.lines) {
      map.set(placed.line.id, !matches || placed.line.title.toLowerCase().includes(terms)
        || placed.nodes.some(node => matches.has(eventDisplayKey(placed.line.id, node.node.eventId))));
    }
    return map;
  }, [layout.lines, matches, terms]);
  const visibleLeft = -x / zoom;
  const visibleRight = (frameWidth - x) / zoom;
  const focusLine = layout.lines.find(placed => placed.line.id === selectedLine) ?? null;
  const nodeCount = layout.lines.reduce((total, placed) => total + placed.nodes.length, 0);
  // 关系端点可能不是关键节点，落到拥有该事件的节点上
  const points = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    for (const placed of layout.lines) {
      for (const node of placed.nodes) {
        for (const id of node.node.eventIds) if (!map.has(id)) map.set(id, { x: node.x, y: node.y });
        map.set(node.node.eventId, { x: node.x, y: node.y });
      }
    }
    return map;
  }, [layout.lines]);
  const focusPoint = selected ? points.get(selected) : undefined;
  const relatedPaths = useMemo(() => {
    if (!showRelations || !focusPoint || !selected) return [];
    return book.relations.flatMap((relation, index) => {
      if (relation.source_id !== selected && relation.target_id !== selected) return [];
      const otherId = relation.source_id === selected ? relation.target_id : relation.source_id;
      const target = points.get(otherId);
      if (!target || (target.x === focusPoint.x && target.y === focusPoint.y)) return [];
      const middle = (focusPoint.x + target.x) / 2;
      const lift = Math.min(56, Math.abs(target.x - focusPoint.x) * 0.14) + 12;
      return [{
        key: relation.relation_id ?? `relation-${index}`,
        d: `M ${focusPoint.x} ${focusPoint.y} C ${middle} ${focusPoint.y - lift}, ${middle} ${target.y - lift}, ${target.x} ${target.y}`,
        color: eventLineColor(focusLine?.line.id ?? layout.lines[0].line.id, focusLine?.line.colorIndex ?? layout.lines[0].line.colorIndex),
      }];
    });
  }, [book.relations, focusLine, focusPoint, layout.lines, points, selected, showRelations]);

  return <div
    ref={hostRef}
    aria-label="事件线画布"
    className="relative min-h-0 min-w-0 flex-1 cursor-grab select-none overflow-hidden bg-surface"
    onPointerDown={event => {
      if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
      event.preventDefault();
      window.getSelection()?.removeAllRanges();
      drag.current = { startX: event.clientX, startY: event.clientY, viewX: x, viewY: y };
      event.currentTarget.setPointerCapture(event.pointerId);
    }}
    onPointerMove={event => {
      if (!drag.current) return;
      onPan(drag.current.viewX + event.clientX - drag.current.startX, drag.current.viewY + event.clientY - drag.current.startY);
    }}
    onPointerUp={() => { drag.current = null; }}
    onPointerCancel={() => { drag.current = null; }}
    onLostPointerCapture={() => { drag.current = null; }}>
    <div className="absolute left-0 top-0" style={{ width: layout.width, height: layout.height, transform: `translate(${x}px, ${y}px) scale(${zoom})`, transformOrigin: "0 0" }}>
      <svg className="pointer-events-none absolute inset-0 overflow-visible" width={layout.width} height={layout.height} role="img" aria-label="全书事件树">
        <desc>{`${layout.lines.length} 条叙事线，左侧为线名与事件数，右侧按顺序排开全部事件树节点`}</desc>
        {layout.lines.map((placed, index) => {
          const dimmed = lineMatches.get(placed.line.id) === false;
          const active = placed.line.id === selectedLine;
          return <g key={placed.line.id} opacity={dimmed ? 0.3 : 1}>
            {index > 0 && <line x1={24} y1={placed.y - layout.rowPitch / 2} x2={layout.width - 24} y2={placed.y - layout.rowPitch / 2} stroke="hsl(var(--border))" strokeOpacity={0.35} />}
            {active && <rect x={22} y={placed.y - (layout.rowPitch - 6) / 2} width={Math.max(0, Math.min(layout.width - 44, 1400))} height={layout.rowPitch - 6} rx={5} fill={placed.color} fillOpacity={0.06} />}
            {active && <rect x={22} y={placed.y - (layout.rowPitch - 6) / 2} width={3} height={layout.rowPitch - 6} rx={1.5} fill={placed.color} />}
            <line x1={layout.trackStart} y1={placed.y} x2={layout.width - 24} y2={placed.y} stroke="hsl(var(--border))" strokeOpacity={0.5} strokeWidth={1} />
            <path data-line-path={placed.line.id} d={placed.path} fill="none" stroke={placed.color} strokeWidth={active ? 2 : 1.5} strokeOpacity={active ? 0.9 : 0.62} strokeLinecap="round" />
          </g>;
        })}
        {relatedPaths.map(path => <path key={path.key} data-line-relation="true" d={path.d} fill="none" stroke={path.color} strokeWidth={1.2} strokeDasharray="4 5" strokeOpacity={0.55} />)}
        {layout.lines.map(placed => {
          const dimmed = lineMatches.get(placed.line.id) === false;
          return <g key={`nodes-${placed.line.id}`} opacity={dimmed ? 0.2 : 1}>
            {placed.nodes.map(placedNode => {
              const owns = selected === placedNode.node.eventId || placedNode.node.eventIds.includes(selected ?? "");
              const active = owns && (!selectedLine || selectedLine === placed.line.id);
              const matched = matches ? matches.has(eventDisplayKey(placed.line.id, placedNode.node.eventId)) : true;
              return <g key={placedNode.node.eventId}>
                {active && <circle cx={placedNode.x} cy={placedNode.y} r={placedNode.size / 2 + 7} fill={placed.color} fillOpacity={0.18} />}
                <circle
                  cx={placedNode.x}
                  cy={placedNode.y}
                  r={active ? placedNode.size / 2 + 1.5 : placedNode.size / 2}
                  fill={active ? placed.color : "hsl(var(--surface))"}
                  stroke={placed.color}
                  strokeWidth={active ? 2 : 1.6}
                  opacity={matched ? 1 : 0.35} />
              </g>;
            })}
          </g>;
        })}
      </svg>

      {layout.lines.map(placed => {
        const dimmed = lineMatches.get(placed.line.id) === false;
        return <div
          key={`rail-${placed.line.id}`}
          data-line-header={placed.line.id}
          data-line-match={dimmed ? "false" : "true"}
          className="absolute text-left transition-opacity"
          style={{ left: 20, top: placed.y - (layout.rowPitch - 6) / 2, width: layout.rail.width - 36, height: layout.rowPitch - 6, opacity: dimmed ? 0.35 : 1 }}>
          <span className="absolute rounded-full" style={{ left: layout.rail.barX - 20, top: "50%", marginTop: -7, width: layout.rail.barWidth, height: 14, background: placed.color }} />
          <span className="absolute left-[34px] top-[5px] max-w-[150px] truncate text-[12.5px] font-semibold leading-4 text-text">{placed.line.title}</span>
          <span className="absolute left-[34px] top-[24px] text-[10.5px] leading-3 text-text-muted">{placed.line.nodes.length} 个节点 · {placed.line.eventCount} 个事件</span>
        </div>;
      })}

      {layout.lines.map(placed => placed.nodes.map(placedNode => {
        const active = (selected === placedNode.node.eventId || placedNode.node.eventIds.includes(selected ?? ""))
          && (!selectedLine || selectedLine === placed.line.id);
        if (!placedNode.labelVisible && !active) return null;
        const labelWidth = Math.min(108, placedNode.node.displayTitle.length * 12 + 8);
        if (placedNode.x - labelWidth / 2 < visibleLeft || placedNode.x + labelWidth / 2 > visibleRight) return null;
        return <button
          key={`label-${placed.line.id}-${placedNode.node.eventId}`}
          type="button"
          aria-hidden="true"
          tabIndex={-1}
          title={placedNode.node.title}
          data-line-node-label={placedNode.node.eventId}
          className={`absolute truncate text-center text-[11px] leading-4 outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${active ? "rounded border px-1.5 font-semibold" : "font-medium text-text-muted hover:text-text"}`}
          style={{
            left: placedNode.x - labelWidth / 2,
            top: placedNode.labelY - 16,
            width: labelWidth,
            color: active ? placed.color : undefined,
            background: active ? "hsl(var(--surface))" : "transparent",
            borderColor: active ? "hsl(var(--border))" : "transparent",
          }}
          onClick={() => onSelect(placedNode.node.eventId, placed.line.id)}>
          {placedNode.node.displayTitle}
        </button>;
      }))}

      {layout.lines.map(placed => placed.nodes.map(placedNode => {
        const owns = selected === placedNode.node.eventId || placedNode.node.eventIds.includes(selected ?? "");
        const active = owns && (!selectedLine || selectedLine === placed.line.id);
        const matched = matches ? matches.has(eventDisplayKey(placed.line.id, placedNode.node.eventId)) : true;
        return <button
          key={`hit-${placed.line.id}-${placedNode.node.eventId}`}
          type="button"
          aria-label={placedNode.node.title}
          title={`${placedNode.node.title} · ${placedNode.node.eventIds.length} 个事件`}
          aria-pressed={active}
          data-line-node={placedNode.node.eventId}
          data-line-node-dimmed={matched ? "false" : "true"}
          className="absolute rounded-full border-0 bg-transparent p-0 outline-none"
          style={{ left: placedNode.x - 10, top: placedNode.y - 10, width: 20, height: 20 }}
          onClick={() => onSelect(placedNode.node.eventId, placed.line.id)} />;
      }))}

      <div className="absolute flex items-center gap-2" style={{ left: 24, top: 20 }}>
        <span aria-label="事件线数" className="text-[12px] font-semibold text-text"><strong className="mr-1 text-[15px] font-semibold text-text">{layout.lines.length}</strong>条叙事线</span>
        <span className="text-[10.5px] text-text-muted">{nodeCount} 个事件树节点</span>
        <span aria-label="事件数" className="text-[10.5px] text-text-muted">{book.counts.all_events} 个事件</span>
      </div>
      <div className="absolute text-[10.5px] tracking-[0.35px] text-text-muted" style={{ left: 24, top: 68 }}>叙事线 / 事件数量</div>
      <div className="absolute text-[10.5px] tracking-[0.35px] text-text-muted" style={{ left: layout.trackStart, top: 43 }}>事件树节点</div>
      <div className="pointer-events-none absolute whitespace-nowrap text-[10.5px] text-text-muted" style={{ right: 24, top: 43 }}>
        {bookTitle} · 点击节点查看所属事件
      </div>
    </div>
  </div>;
}
