import { useMemo, useState } from "react";
import type { EventForestNode, EventForestResponse, EventForestTree } from "@/api/types";
import { layoutEventTree, treeNodeCount } from "./eventTreeLayout";

interface GrowthForestCanvasProps {
  forest: EventForestResponse;
  trees: EventForestTree[];
  nodes: Map<string, EventForestNode>;
  onOpenTree: (tree: EventForestTree) => void;
  focusChapterOrder?: number | null;
}

const SCENE_WIDTH = 1200;
const FOREST_COLUMNS = 9;

/** 整片森林以章节为土壤，缩微树的点线仍对应各自的真实事件结构 */
export function GrowthForestCanvas({ forest, trees, nodes, onOpenTree, focusChapterOrder }: GrowthForestCanvasProps) {
  const [hoveredTreeId, setHoveredTreeId] = useState<string | null>(null);
  const chapters = useMemo(
    () => focusChapterOrder != null
      ? [focusChapterOrder]
      : [...new Set(forest.event_nodes.map((node) => node.chapter_order))].sort((a, b) => a - b),
    [forest, focusChapterOrder],
  );
  const focused = focusChapterOrder != null;
  const columns = focused ? 1 : Math.max(1, Math.min(FOREST_COLUMNS, chapters.length));
  const rows = Math.ceil(chapters.length / columns);
  const focusColumns = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(trees.length))));
  const focusRows = Math.ceil(trees.length / focusColumns);
  const rowHeight = focused ? Math.max(486, 175 + (focusRows - 1) * 125 + 61) : 167;
  const sceneHeight = rows * rowHeight + 25;
  const cellWidth = 1120 / columns;
  const visibleByChapter = useMemo(() => {
    const groups = new Map<number, EventForestTree[]>();
    for (const tree of trees) {
      const chapter = nodes.get(tree.root_event_id)?.chapter_order;
      if (chapter !== undefined) groups.set(chapter, [...(groups.get(chapter) ?? []), tree]);
    }
    return groups;
  }, [nodes, trees]);
  const layouts = useMemo(
    () => new Map(trees.map((tree) => [tree.tree_id, layoutEventTree(tree, nodes)])),
    [nodes, trees],
  );
  const hoveredTree = trees.find((tree) => tree.tree_id === hoveredTreeId);
  const hoveredRoot = hoveredTree ? nodes.get(hoveredTree.root_event_id) : null;
  const foreshadowIds = useMemo(
    () => new Set(forest.foreshadowing_edges.map((edge) => edge.tree_id)),
    [forest],
  );

  return (
    <section aria-label="整片事件森林" className="flex min-h-0 flex-1 flex-col rounded-2xl border border-border/70 bg-surface/80 shadow-sm">
      <div className="flex shrink-0 items-center justify-between gap-3 px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold text-text">{focused ? `第 ${focusChapterOrder} 章的生长林` : "故事生长林"}</h2>
          <p className="text-xs text-text-muted">{focused ? `本章锚定 ${trees.length} 棵事件树 · 点击放大` : "每棵小树都是一组真实事件 · 点击放大"}</p>
        </div>
        <div className="flex gap-3 text-xs text-text-muted" aria-label="森林图例">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-primary" />事件树</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-500" />伏笔树</span>
        </div>
      </div>
      <svg className="min-h-0 w-full flex-1" viewBox={`0 0 ${SCENE_WIDTH} ${sceneHeight}`} aria-label={`按章节排列的 ${trees.length} 棵事件树`}>
        <defs>
          <linearGradient id="forest-paper" x2="0" y2="1"><stop stopColor="#fff9f5"/><stop offset="1" stopColor="#f4ebe7"/></linearGradient>
          <linearGradient id="forest-soil" x2="0" y2="1"><stop stopColor="#d4b9ab"/><stop offset="1" stopColor="#b89b8c"/></linearGradient>
          <radialGradient id="forest-crown" cx=".45" cy=".25"><stop stopColor="#f3b8a2" stopOpacity=".92"/><stop offset="1" stopColor="#c77766" stopOpacity=".72"/></radialGradient>
          <radialGradient id="forest-crown-gold" cx=".45" cy=".25"><stop stopColor="#f6dc9a" stopOpacity=".96"/><stop offset="1" stopColor="#c79a45" stopOpacity=".8"/></radialGradient>
          <filter id="forest-soft-shadow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2"/></filter>
        </defs>
        <rect width={SCENE_WIDTH} height={sceneHeight} fill="url(#forest-paper)" />
        {focused && Array.from({ length: focusRows }, (_, index) => (
          <path key={`focus-ground-${index}`} d={`M 95 ${214 + index * 125} Q 600 ${205 + index * 125} 1105 ${214 + index * 125}`} fill="none" stroke="#d4b9ab" strokeWidth="2.5" opacity=".65" />
        ))}
        {!focused && Array.from({ length: rows }, (_, row) => {
          const groundY = (row + 1) * rowHeight - 22;
          return (
            <g key={`ground-${row}`}>
              <path d={`M 20 ${groundY} C 260 ${groundY - 8} 390 ${groundY + 7} 610 ${groundY} S 980 ${groundY - 7} 1180 ${groundY}`} fill="none" stroke="url(#forest-soil)" strokeWidth="3" opacity=".82" />
              <path d={`M 20 ${groundY + 4} C 260 ${groundY - 4} 390 ${groundY + 11} 610 ${groundY + 4} S 980 ${groundY - 3} 1180 ${groundY + 4}`} fill="none" stroke="#e5d6cc" strokeWidth="8" opacity=".35" />
            </g>
          );
        })}
        {chapters.map((chapter, chapterIndex) => {
          const row = Math.floor(chapterIndex / columns);
          const column = chapterIndex % columns;
          const centerX = 40 + (column + 0.5) * cellWidth;
          const groundY = (row + 1) * rowHeight - 22;
          const chapterTrees = visibleByChapter.get(chapter) ?? [];
          const miniColumns = focused ? focusColumns : Math.min(3, Math.max(1, Math.ceil(Math.sqrt(chapterTrees.length))));
          const miniGap = focused ? 280 : Math.min(34, (cellWidth - 15) / miniColumns);
          return (
            <g key={chapter}>
              <circle cx={centerX} cy={groundY + 1} r="3" fill="#a97e70" />
              <text x={centerX} y={groundY + 18} textAnchor="middle" fill="#92776e" fontSize="10" fontWeight="600">第 {chapter} 章</text>
              {chapterTrees.map((tree, treeIndex) => {
                const rowIndex = Math.floor(treeIndex / miniColumns);
                const columnIndex = treeIndex % miniColumns;
                const x = centerX + (columnIndex - (miniColumns - 1) / 2) * miniGap;
                const y = focused ? 175 + rowIndex * 125 : groundY - 22 - rowIndex * 34;
                const layout = layouts.get(tree.tree_id);
                const root = nodes.get(tree.root_event_id);
                const isHovered = tree.tree_id === hoveredTreeId;
                const isForeshadow = foreshadowIds.has(tree.tree_id);
                return (
                  <g
                    key={tree.tree_id}
                    role="button"
                    tabIndex={0}
                    aria-label={`第 ${chapter} 章事件树：${root?.description ?? "未知事件"}，${treeNodeCount(tree)} 个节点`}
                    data-tree-id={tree.tree_id}
                    transform={`translate(${x} ${y})${focused ? " scale(2.6)" : ""}`}
                    onClick={() => onOpenTree(tree)}
                    onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpenTree(tree); } }}
                    onMouseEnter={() => setHoveredTreeId(tree.tree_id)}
                    onMouseLeave={() => setHoveredTreeId(null)}
                    onFocus={() => setHoveredTreeId(tree.tree_id)}
                    onBlur={() => setHoveredTreeId(null)}
                    className="cursor-pointer outline-none focus-visible:opacity-75"
                  >
                    {isHovered && <circle r="19" fill={isForeshadow ? "#efd896" : "#e3aaa1"} opacity=".3" filter="url(#forest-soft-shadow)" />}
                    {/* 低饱和树冠是背景造型；高饱和点线才对应事件及父子关系 */}
                    <g aria-hidden="true" pointerEvents="none" transform={`translate(0 -8) scale(${Math.min(1.12, .75 + treeNodeCount(tree) * .05)}) translate(0 8)`}>
                      <path d="M -11 -1 C -19 -5 -19 -13 -12 -16 C -14 -24 -5 -29 0 -23 C 7 -30 15 -23 13 -17 C 22 -13 18 -5 11 -1 Q 0 3 -11 -1 Z" fill={isForeshadow ? "url(#forest-crown-gold)" : "url(#forest-crown)"} opacity=".68" />
                      <path d="M -11 -7 Q -17 -13 -10 -17 M 3 -21 Q 8 -26 13 -18 M 8 -6 Q 14 -11 17 -10" fill="none" stroke="#fff7eb" strokeWidth="1" opacity=".55" />
                    </g>
                    <path aria-hidden="true" pointerEvents="none" d="M -4 15 Q -1 12 0 7 Q 1 12 5 15 M -2 13 Q -7 16 -10 16 M 2 13 Q 7 16 10 16" fill="none" stroke="#b58a78" strokeWidth="1.2" strokeLinecap="round" opacity=".8" />
                    {layout?.connections.map((edge) => {
                      const source = layout.points.get(edge.source);
                      const target = layout.points.get(edge.target);
                      if (!source || !target) return null;
                      const x1 = (source.x - 360) * .045;
                      const y1 = (source.y - 285) * .055;
                      const x2 = (target.x - 360) * .045;
                      const y2 = (target.y - 285) * .055;
                      return <path key={`${edge.source}-${edge.target}`} d={`M ${x1} ${y1} Q ${(x1 + x2) / 2} ${(y1 + y2) / 2 - 2} ${x2} ${y2}`} fill="none" stroke={edge.kind === "main" ? "#96584c" : "#b97969"} strokeWidth={edge.kind === "main" ? 1.8 : 1.15} strokeLinecap="round" />;
                    })}
                    {[...(layout?.points ?? [])].map(([id, point]) => {
                      const role = nodes.get(id)?.cause_role;
                      const px = (point.x - 360) * .045;
                      const py = (point.y - 285) * .055;
                      return role === "secondary"
                        ? <ellipse key={id} cx={px} cy={py} rx="2.2" ry="1.5" transform={`rotate(-25 ${px} ${py})`} fill={isForeshadow ? "#c89a36" : "#c78171"} />
                        : <circle key={id} cx={px} cy={py} r={role === "root" ? 2.6 : 1.7} fill={isForeshadow ? "#c89a36" : "#9f5b4e"} />;
                    })}
                    <rect x="-16" y="-17" width="32" height="34" fill="transparent" />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border/60 px-5 py-2 text-xs text-text-muted">
        <span className="min-w-0 truncate">{hoveredRoot ? `第 ${hoveredRoot.chapter_order} 章 · ${hoveredRoot.description}` : focused ? "本章每棵树都对应真实事件；点击查看因果结构" : "沿章节顺序浏览森林；枝干和叶片对应实际事件"}</span>
        <span className="shrink-0">{forest.causal_edges.length === 0 ? "暂无树间因果关系" : `${forest.causal_edges.length} 条树间因果关系`}</span>
      </div>
    </section>
  );
}
