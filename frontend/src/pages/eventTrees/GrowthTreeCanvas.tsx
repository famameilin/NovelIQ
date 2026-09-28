import { useMemo, useRef, useState } from "react";
import { ArrowLeft, Minus, Plus, Scan } from "lucide-react";
import type { EventForestNode, EventForestTree } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { layoutEventTree, treeNodeCount } from "./eventTreeLayout";

const CROWN_PATH = "M 352 58 C 331 36 301 42 286 59 C 258 49 237 64 231 85 C 198 86 188 113 203 138 C 170 158 181 186 204 200 C 179 230 195 261 223 265 C 211 300 237 322 267 315 C 272 346 312 358 338 341 C 357 363 393 354 407 338 C 437 351 467 333 464 309 C 499 303 509 275 491 252 C 521 231 515 202 490 189 C 520 163 501 132 475 127 C 480 93 451 74 424 78 C 409 48 377 40 352 58 Z";

interface GrowthTreeCanvasProps {
  tree: EventForestTree;
  nodes: Map<string, EventForestNode>;
  selectedEventId: string;
  foreshadowStatus?: string;
  onSelectEvent: (eventId: string) => void;
  onBack: () => void;
}

function edgePath(source: { x: number; y: number }, target: { x: number; y: number }, main: boolean): string {
  if (main) {
    const middleY = (source.y + target.y) / 2;
    return `M ${source.x} ${source.y} C ${source.x - 8} ${middleY + 15}, ${target.x + 8} ${middleY - 15}, ${target.x} ${target.y}`;
  }
  const bendX = source.x + (target.x - source.x) * .45;
  return `M ${source.x} ${source.y} C ${bendX} ${source.y - 12}, ${bendX} ${target.y + 14}, ${target.x} ${target.y}`;
}

/** 树干和枝叶都来自真实事件节点；木纹、光影只承担拟物表现 */
export function GrowthTreeCanvas({
  tree, nodes, selectedEventId, foreshadowStatus, onSelectEvent, onBack,
}: GrowthTreeCanvasProps) {
  const layout = useMemo(() => layoutEventTree(tree, nodes), [tree, nodes]);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const root = nodes.get(tree.root_event_id);
  const unlinked = new Set(layout.unlinked);

  function changeZoom(factor: number) {
    setZoom((current) => Math.max(.75, Math.min(2.8, Number((current * factor).toFixed(2)))));
  }

  function handlePointerDown(event: React.PointerEvent<SVGSVGElement>) {
    if ((event.target as Element).closest("[data-event-id]")) return;
    drag.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (!drag.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    setPan({
      x: drag.current.panX + (event.clientX - drag.current.x) * 720 / rect.width,
      y: drag.current.panY + (event.clientY - drag.current.y) * 560 / rect.height,
    });
  }

  return (
    <section aria-label="事件树结构" className="flex min-h-0 flex-1 flex-col rounded-2xl border border-border/70 bg-surface/80 shadow-sm">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onBack} aria-label="返回整片森林"><ArrowLeft className="mr-1 h-4 w-4" />森林</Button>
          <span className="min-w-0 truncate text-sm font-semibold text-text" title={root?.description}>{root?.description ?? "事件树"}</span>
          <Badge variant="outline" className="shrink-0">{treeNodeCount(tree)} 节点</Badge>
          {foreshadowStatus && <Badge variant="outline" className="shrink-0">伏笔</Badge>}
        </div>
        <div className="flex shrink-0 items-center gap-1" aria-label="树图缩放">
          <Button variant="ghost" size="sm" aria-label="缩小树图" onClick={() => changeZoom(1 / 1.25)}><Minus className="h-4 w-4" /></Button>
          <Button variant="ghost" size="sm" aria-label="放大树图" onClick={() => changeZoom(1.25)}><Plus className="h-4 w-4" /></Button>
          <Button variant="ghost" size="sm" aria-label="适应画布" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}><Scan className="h-4 w-4" /></Button>
        </div>
      </div>
      <svg
        className="min-h-0 w-full flex-1 touch-none"
        viewBox="0 0 720 560"
        aria-label="树干表示主链，枝叶表示次因旁支"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={(event) => { drag.current = null; if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture?.(event.pointerId); }}
        onPointerCancel={() => { drag.current = null; }}
      >
        <defs>
          <radialGradient id="tree-paper"><stop stopColor="#fff9f3"/><stop offset="1" stopColor="#f1e6e0"/></radialGradient>
          <linearGradient id="tree-bark" x1="0" x2="1"><stop stopColor="#9b5549"/><stop offset=".48" stopColor="#bb7660"/><stop offset="1" stopColor="#7c443d"/></linearGradient>
          <linearGradient id="tree-branch" x1="0" x2="1"><stop stopColor="#b46c58"/><stop offset="1" stopColor="#d1987c"/></linearGradient>
          <linearGradient id="tree-leaf" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#f4c9b6"/><stop offset=".55" stopColor="#d98577"/><stop offset="1" stopColor="#a85855"/></linearGradient>
          <radialGradient id="tree-crown" cx=".45" cy=".25"><stop stopColor="#f7d6b8" stopOpacity=".86"/><stop offset=".65" stopColor="#e9aa94" stopOpacity=".66"/><stop offset="1" stopColor="#c9776a" stopOpacity=".3"/></radialGradient>
          <radialGradient id="tree-crown-light" cx=".4" cy=".3"><stop stopColor="#fff0da" stopOpacity=".78"/><stop offset="1" stopColor="#f2c6ab" stopOpacity=".06"/></radialGradient>
          <pattern id="tree-foliage-texture" width="39" height="35" patternUnits="userSpaceOnUse">
            <path d="M 7 8 Q 14 2 19 8 Q 14 14 7 8 M 27 24 Q 33 18 37 25 Q 31 29 27 24" fill="#a75d52" opacity=".25" />
            <path d="M 8 8 L 18 8 M 28 24 L 36 24" fill="none" stroke="#fff0df" strokeWidth=".8" opacity=".45" />
          </pattern>
          <radialGradient id="tree-bud"><stop stopColor="#ffe9ab"/><stop offset="1" stopColor="#c89635"/></radialGradient>
          <filter id="tree-shadow" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="2" dy="3" stdDeviation="3" floodColor="#7d5345" floodOpacity=".2"/></filter>
        </defs>
        <rect width="720" height="560" fill="url(#tree-paper)" />
        <path d="M 45 515 Q 350 495 675 515" fill="none" stroke="#cfb7a8" strokeWidth="5" opacity=".55" />
        <path d="M 120 530 C 220 508 290 512 360 514 C 450 510 540 519 630 532" fill="none" stroke="#dcc6b6" strokeWidth="15" opacity=".28" />
        <g transform={`translate(${360 + pan.x} ${280 + pan.y}) scale(${zoom}) translate(-360 -280)`}>
          {/* 树冠、树皮和根系是拟物背景；可点击的节点和关系线在其上单独绘制 */}
          <g aria-hidden="true" pointerEvents="none">
            <path d={CROWN_PATH} fill="url(#tree-crown)" />
            <path d={CROWN_PATH} fill="url(#tree-foliage-texture)" opacity=".55" />
            <ellipse cx="295" cy="127" rx="80" ry="76" fill="url(#tree-crown-light)" />
            <ellipse cx="429" cy="187" rx="70" ry="95" fill="url(#tree-crown-light)" opacity=".65" />
            <path d="M 344 506 C 351 459 348 405 353 357 C 357 294 355 207 357 73 C 360 66 364 66 366 73 C 368 191 368 294 371 357 C 374 417 374 466 382 506 Z" fill="url(#tree-bark)" stroke="#8b5043" strokeWidth="1.3" />
            <path d="M 350 506 C 344 512 326 515 311 516 M 354 496 C 349 510 337 521 322 524 M 374 501 C 384 512 402 515 420 516 M 371 496 C 379 509 390 522 407 525" fill="none" stroke="#a36a55" strokeWidth="5" strokeLinecap="round" opacity=".75" />
            <path d="M 357 105 C 352 199 359 261 357 355 C 356 411 354 459 351 487 M 366 133 C 370 242 362 302 369 396 C 370 436 371 462 376 489" fill="none" stroke="#e4ac8d" strokeWidth="1.3" opacity=".5" />
          </g>
          {layout.connections.filter((edge) => edge.kind === "main").map((edge) => {
            const source = layout.points.get(edge.source);
            const target = layout.points.get(edge.target);
            if (!source || !target) return null;
            const path = edgePath(source, target, true);
            return <g key={`${edge.source}-${edge.target}`}>
              <path d={path} fill="none" stroke="#73463d" strokeWidth="11" strokeLinecap="round" opacity=".12" transform="translate(3 2)" />
              <path data-parent-id={edge.source} data-child-id={edge.target} d={path} fill="none" stroke="url(#tree-bark)" strokeWidth="8" strokeLinecap="round" />
              <path d={path} fill="none" stroke="#e8ac8e" strokeWidth="1.5" strokeLinecap="round" opacity=".48" transform="translate(-3 0)" />
            </g>;
          })}
          {layout.connections.filter((edge) => edge.kind === "secondary").map((edge) => {
            const source = layout.points.get(edge.source);
            const target = layout.points.get(edge.target);
            if (!source || !target) return null;
            return <path key={`${edge.source}-${edge.target}`} data-parent-id={edge.source} data-child-id={edge.target} d={edgePath(source, target, false)} fill="none" stroke="url(#tree-branch)" strokeWidth="5" strokeLinecap="round" filter="url(#tree-shadow)" />;
          })}
          {[...layout.points].map(([eventId, point]) => {
            const node = nodes.get(eventId);
            if (!node) return null;
            const selected = selectedEventId === eventId;
            const secondary = node.cause_role === "secondary";
            const missing = unlinked.has(eventId);
            const label = `${node.cause_role === "root" ? "事件起点" : secondary ? "次因旁支" : "主链事件"}：${node.description}`;
            return <g
              key={eventId}
              role="button"
              tabIndex={0}
              aria-label={label}
              aria-pressed={selected}
              data-event-id={eventId}
              data-parent-event-id={node.parent_event_id ?? ""}
              transform={`translate(${point.x} ${point.y})`}
              onClick={() => onSelectEvent(eventId)}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelectEvent(eventId); } }}
              className="cursor-pointer outline-none"
            >
              {selected && <circle r={secondary ? 25 : 20} fill="none" stroke="#e97863" strokeWidth="2" strokeDasharray="4 5" />}
              {secondary ? (
                <g filter="url(#tree-shadow)">
                  <ellipse cx="0" cy="0" rx="18" ry="10" transform="rotate(-27)" fill={missing ? "#b5aaa3" : "url(#tree-leaf)"} stroke="#fff2e9" strokeWidth="2" />
                  <path d="M -12 6 Q 1 -1 13 -7" fill="none" stroke="#fff1e9" strokeWidth="1" opacity=".7" />
                </g>
              ) : (
                <g filter="url(#tree-shadow)">
                  <circle r={node.cause_role === "root" ? 13 : 9} fill={node.cause_role === "root" && foreshadowStatus ? "url(#tree-bud)" : "url(#tree-bark)"} stroke="#fff3ea" strokeWidth="2" />
                  <circle r={node.cause_role === "root" ? 5 : 3} fill="none" stroke="#f2c7a5" strokeWidth="1" opacity=".65" />
                </g>
              )}
              {missing && <text x="0" y="4" textAnchor="middle" fontSize="12" fontWeight="700" fill="white">?</text>}
              {selected && <g>
                <rect x={secondary && point.x > 360 ? -198 : 23} y="-46" width="175" height="27" rx="9" fill="#fffaf7" stroke="#d6a99b" />
                <text x={secondary && point.x > 360 ? -187 : 34} y="-28" fontSize="12" fontWeight="600" fill="#5a3b35">{node.description.length > 11 ? `${node.description.slice(0, 11)}…` : node.description}</text>
              </g>}
            </g>;
          })}
        </g>
        {layout.unlinked.length > 0 && <text x="35" y="548" fontSize="11" fill="#86736a">挂接点待确认：{layout.unlinked.length} 个节点（未绘制连线）</text>}
      </svg>
      <div className="flex shrink-0 items-center justify-between px-4 py-2 text-xs text-text-muted">
        <span>树干亮点：主链 · 叶片：次因 · 连线只连接已核实的父子事件</span>
        <span>拖动平移 · 放大查看</span>
      </div>
    </section>
  );
}
