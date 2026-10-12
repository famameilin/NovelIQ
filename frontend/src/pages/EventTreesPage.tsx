import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { BookOpen, List, Maximize2, Minus, Plus, Search, X } from "lucide-react";
import { getEventTrees, getEventTreeNode, getEventTreeBook } from "@/api/results";
import { getNovel } from "@/api/novels";
import type { NarrativeTreeNode, NarrativeTreeResponse } from "@/api/narrativeTypes";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { FloatingDetail, NarrativeError, NarrativeReader } from "@/components/narrative/NarrativePanels";
import { control, narrativeHeader, narrativeLine, narrativeMuted, narrativePaper, valueText } from "@/components/narrative/presentation";
import { useNarrativeSize } from "@/components/narrative/useNarrativeSize";
import { circleConnectionPath, organizationBranchPaths, organizationFieldLayout, type FieldBox, type FieldPosition } from "@/components/narrative/organizationFieldLayout";
import { organizationConnections } from "@/components/narrative/organizationConnections";
import { fitTree, fitTreeBounds, treeCenter, zoomTree } from "@/components/narrative/treeViewport";
import { useNarrativeState } from "@/components/narrative/useNarrativeState";
import { shouldWriteBackTaskUrl, useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { useNovelStore } from "@/store/novelStore";

interface TreeState { selected: string | null; q: string; chapter: number | null; scale: number; x: number; y: number; reader: boolean }
const kindLabels: Record<string, string> = { root: "全书核心", arc: "叙事线", group: "局部事件组", event: "原子事件", unassigned: "待归属" };
const relationLabels: Record<string, string> = { organization: "组织归属", local_parent: "局部父子", causal: "因果关联", foreshadowing: "伏笔照应", reference: "跨线引用" };
const foreshadowingLabels = { open: "待回收", reinforced: "持续强化", likely_paid_off: "疑似回收" };
const minimumReadingScale = .85;
const canvasControl = "inline-flex h-8 items-center justify-center gap-2 rounded-md px-2 text-xs text-text-muted outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-primary/40";

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
  const initial = useQuery({ queryKey: ["event-trees-book", novelId, task], queryFn: ({ signal }) => getEventTreeBook(novelId!, task!, signal), enabled: !!novelId && !!task, retry: false, staleTime: 0, refetchOnMount: "always" });
  return <AnalysisWorkspace title="事件树" headerClassName={`${narrativeHeader} py-3 [&_h1]:after:-bottom-[13px]`} contentClassName="py-0" className={`${narrativePaper} min-w-[860px] px-7 pb-2 pt-0`}>
    {!task && <p>请先选择分析任务</p>}
    {initial.isPending && task && <p className="p-6 text-sm text-text-muted">正在读取全书事件树…</p>}
    {initial.isError && <NarrativeError error={initial.error} retry={() => void initial.refetch()} />}
    {!initial.isError && initial.data && novelId && <TreeWorkspace key={`${novelId}:${initial.data.run_id}`} novelId={novelId} initial={initial.data} />}
  </AnalysisWorkspace>;
}

function TreeWorkspace({ novelId, initial }: { novelId: string; initial: NarrativeTreeResponse }) {
  const runId = initial.run_id;
  const cachedNovel = useNovelStore(state => state.getNovelById(novelId));
  const novel = useQuery({ queryKey: ["novel", novelId], queryFn: () => getNovel(novelId), enabled: !cachedNovel, staleTime: 5 * 60 * 1000, gcTime: 10 * 60 * 1000, retry: false });
  const bookTitle = cachedNovel?.title ?? novel.data?.title;
  // 全书节点始终参与布局与绘制，页面只保存选择和视口，不保存节点可见性
  const [view, update] = useNarrativeState<TreeState>(`${novelId}:${runId}:event-trees`, { selected: null, q: "", chapter: null, scale: 0, x: 0, y: 0, reader: false });
  const [focusTarget, setFocusTarget] = useState<{ id: string; overview?: boolean } | null>(view.selected ? { id: view.selected } : view.scale > 0 ? null : { id: "root", overview: true });
  const arrowId = `event-tree-arrow-${useId()}`;
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [host, size] = useNarrativeSize();
  const drag = useRef<{ x: number; y: number; viewX: number; viewY: number } | null>(null);
  const search = useInfiniteQuery({ queryKey: ["organization-search", novelId, runId, view.q, view.chapter], queryFn: ({ pageParam, signal }) => getEventTrees(novelId, runId, { q: view.q, chapterId: view.chapter ?? undefined, cursor: pageParam, signal }), initialPageParam: undefined as string | undefined, getNextPageParam: page => page.next_cursor ?? undefined, enabled: !!view.q || view.chapter != null, retry: false, staleTime: 0 });
  const detail = useQuery({ queryKey: ["organization-detail", novelId, runId, view.selected], queryFn: ({ signal }) => getEventTreeNode(novelId, runId, view.selected!, signal), enabled: !!view.selected, retry: false, staleTime: 0 });
  const nodes = useMemo(() => {
    const result = new Map(initial.nodes.map(node => [node.node_id, node]));
    search.data?.pages.forEach(page => page.nodes.forEach(node => result.set(node.node_id, node)));
    detail.data?.path.forEach(node => result.set(node.node_id, node));
    return result;
  }, [initial.nodes, search.data, detail.data]);
  const bookNodes = useMemo(() => [...nodes.values()], [nodes]);
  const layout = useMemo(() => organizationFieldLayout(bookNodes, initial.arcs, size.width), [bookNodes, initial.arcs, size.width]);
  const positions = layout.positions;
  const canvasWidth = layout.width, canvasHeight = layout.height;
  const frame = { width: size.width, height: size.height, canvasWidth, canvasHeight };
  const scale = view.scale > 0 ? view.scale : 1;
  const { x: centeredX, y: centeredY } = treeCenter(frame, scale);
  const centerNodes = bookNodes.filter(node => node.kind === "root" || node.parent_id === "root").map(node => positions.get(node.node_id)!).filter(Boolean);
  const coreLeft = Math.min(...centerNodes.map(node => node.left)), coreTop = Math.min(...centerNodes.map(node => node.top));
  const coreWidth = Math.max(...centerNodes.map(node => node.left + node.width)) - coreLeft, coreHeight = Math.max(...centerNodes.map(node => node.top + node.height)) - coreTop;
  useEffect(() => {
    const canvas = host.current;
    if (!canvas) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      setFocusTarget(null);
      const rect = canvas.getBoundingClientRect();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1;
      const delta = Math.max(-120, Math.min(120, event.deltaY * unit));
      // 使用最新视口累积滚轮输入，鼠标下的世界坐标在每一帧保持不动
      update(previous => {
        const currentScale = previous.scale > 0 ? previous.scale : 1;
        const nextScale = Math.max(.01, Math.min(1.8, currentScale * Math.exp(-delta * .002)));
        return zoomTree({ ...previous, scale: currentScale }, { width: rect.width, height: rect.height, canvasWidth, canvasHeight }, nextScale, { x: event.clientX - rect.left, y: event.clientY - rect.top });
      });
    };
    // React 的被动滚轮监听不能阻止页面滚动，这里只在画布内接管滚轮
    canvas.addEventListener("wheel", wheel, { passive: false });
    return () => canvas.removeEventListener("wheel", wheel);
  }, [host, canvasWidth, canvasHeight, update]);
  const tones = { main: "text-primary", violet: "text-chart-2", teal: "text-chart-3", neutral: narrativeMuted };
  const edges = [...new Map([initial, ...(search.data?.pages ?? []), detail.data ? { edges: detail.data.relations } : undefined].flatMap(page => page?.edges ?? []).map(edge => [`${edge.source_id}:${edge.target_id}:${edge.kind}`, edge])).values()];
  const matches = search.data?.pages.flatMap(page => page.matches) ?? [];
  const selected = detail.data;
  const connections = organizationConnections(edges).filter(edge => nodes.has(edge.source_id) && nodes.has(edge.target_id));
  const related = selected ? organizationConnections(selected.relations).map(edge => ({ ...selected.relations.find(relation => relation.source_id === edge.source_id && relation.target_id === edge.target_id)!, kinds: edge.kinds })) : [];
  const organizationStems = new Map<string, ReturnType<typeof organizationBranchPaths>>();
  for (const source of bookNodes.filter(node => node.kind === "arc" || node.kind === "group")) {
    const a = positions.get(source.node_id);
    const children = connections.filter(edge => edge.source_id === source.node_id && edge.kinds.every(kind => kind === "organization")).map(edge => ({ id: edge.target_id, position: positions.get(edge.target_id)! })).filter(child => !!child.position);
    if (!a || children.length < 2) continue;
    organizationStems.set(source.node_id, organizationBranchPaths(a, children));
  }
  function ancestors(id: string) {
    const result: string[] = [], seen = new Set<string>();
    let parent = nodes.get(id)?.parent_id;
    while (parent && !seen.has(parent)) { seen.add(parent); result.unshift(parent); parent = nodes.get(parent)?.parent_id; }
    return result;
  }
  function select(id: string) {
    update({ selected: id, reader: false, scale: Math.max(scale, minimumReadingScale) });
    setDirectoryOpen(false);
    setFocusTarget({ id });
  }
  function fit() { setFocusTarget(null); update(fitTree(frame)); }
  function fitBranch() {
    const selectedId = view.selected;
    if (!selectedId) return;
    const branch = bookNodes.filter(node => node.node_id === selectedId || ancestors(node.node_id).includes(selectedId)).map(node => positions.get(node.node_id)!).filter(Boolean);
    if (!branch.length) return;
    const left = Math.min(...branch.map(node => node.left)) - 40, top = Math.min(...branch.map(node => node.top)) - 40;
    const right = Math.max(...branch.map(node => node.left + node.width)) + 40, bottom = Math.max(...branch.map(node => node.top + node.height)) + 40;
    const nextScale = Math.min(1, size.width / (right - left), size.height / (bottom - top));
    const centered = treeCenter(frame, nextScale);
    setFocusTarget(null);
    update({ scale: nextScale, x: size.width / 2 - (left + right) / 2 * nextScale - centered.x, y: size.height / 2 - (top + bottom) / 2 * nextScale - centered.y });
  }
  function zoom(delta: number) {
    setFocusTarget(null);
    const point = view.selected ? positions.get(view.selected) : undefined;
    const anchor = point ? { x: centeredX + view.x + point.x * scale, y: centeredY + view.y + point.y * scale } : undefined;
    const visibleAnchor = anchor && anchor.x >= 0 && anchor.x <= size.width && anchor.y >= 0 && anchor.y <= size.height ? anchor : undefined;
    update(zoomTree({ scale, x: view.x, y: view.y }, frame, Math.max(.01, Math.min(1.8, scale + delta)), visibleAnchor));
  }
  const focus = focusTarget ? positions.get(focusTarget.id) : undefined;
  const overviewFocus = focusTarget?.overview ?? false;
  const focusX = focus?.x;
  const focusY = focus?.y;
  useEffect(() => {
    if (focusX == null || focusY == null) return;
    const rect = host.current?.getBoundingClientRect();
    if (!rect || !rect.width || Math.abs(rect.width - size.width) > 1 || Math.abs(rect.height - size.height) > 1) return;
    // 详情列会改变画布宽度，等 ResizeObserver 和布局采用同一尺寸后再定位
    const frame = requestAnimationFrame(() => {
      update(overviewFocus
        ? fitTreeBounds({ width: rect.width, height: rect.height, canvasWidth, canvasHeight }, { left: coreLeft, top: coreTop, width: coreWidth, height: coreHeight })
        : { scale, x: rect.width / 2 - focusX * scale - centeredX, y: rect.height / 2 - focusY * scale - centeredY });
      setFocusTarget(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [focusX, focusY, overviewFocus, scale, centeredX, centeredY, size.width, size.height, canvasWidth, canvasHeight, coreLeft, coreTop, coreWidth, coreHeight, update, host]);
  const label = (node: NarrativeTreeNode) => node.kind === "arc" ? initial.arcs.find(arc => arc.arc_id === node.arc_id)?.kind === "main" ? "核心主线" : "支线" : node.is_foreshadowing_root ? "伏笔事件" : kindLabels[node.kind];
  const boxStyle = (box: FieldBox, position: FieldPosition) => ({ left: box.left - position.left, top: box.top - position.top, width: box.width, height: box.height });
  return <section aria-label="全书事件树" className={`grid min-h-0 min-w-0 flex-1 grid-rows-[minmax(0,1fr)] items-stretch gap-5 ${view.selected ? "grid-cols-[minmax(0,1fr)_370px]" : "grid-cols-[minmax(0,1fr)]"}`}>
    <div className="relative flex min-h-0 min-w-0 flex-col">
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 pb-2 pt-3">
      <div className={`flex items-center gap-2 text-xs ${narrativeMuted}`}><i className="size-1.5 rounded-full bg-primary" /><span>全书归属</span><span className="text-border">/</span><span>{initial.arcs.length} 条叙事线 · {initial.total_events} 个事件</span></div>
      <div className="flex flex-wrap items-center gap-2">
        <label className={`flex w-40 items-center gap-2 border-b py-2 ${narrativeLine} ${narrativeMuted}`}><Search size={14} /><input className="min-w-0 flex-1 bg-transparent text-xs outline-none" aria-label="搜索全书事件" placeholder="查找全书事件" value={view.q} onChange={event => { update({ q: event.target.value }); setDirectoryOpen(true); }} /></label>
        <select aria-label="章节定位" className={`${control} max-w-36`} value={view.chapter ?? ""} onChange={event => { update({ chapter: Number(event.target.value) || null }); setDirectoryOpen(true); }}><option value="">全书 · 章节定位</option>{initial.chapters.map(chapter => <option key={chapter.chapter_id} value={chapter.chapter_id}>{chapter.order}. {chapter.title}</option>)}</select>
        <button className={`${control} border-0`} aria-expanded={directoryOpen} onClick={() => { if (directoryOpen) { setDirectoryOpen(false); update({ q: "", chapter: null }); } else setDirectoryOpen(true); }}><List size={14} />结构目录</button>
      </div>
    </div>

    <aside aria-label="全书结构目录" hidden={!directoryOpen} className={`absolute bottom-16 right-0 top-24 z-20 w-80 max-w-full overflow-y-auto border bg-surface p-5 shadow-xl ${narrativeLine}`}>
      <div className="flex items-center justify-between"><h2 className="text-base font-medium">全书结构</h2><button aria-label="关闭结构目录" className={control} onClick={() => { setDirectoryOpen(false); update({ q: "", chapter: null }); }}><X size={15} /></button></div>
      <p className={`mb-4 mt-2 text-[11px] ${narrativeMuted}`}>{initial.total_events} 个唯一事件 · {initial.arcs.length} 条叙事线</p>
      {(view.q || view.chapter != null) ? <div className={`border-t pt-4 ${narrativeLine}`}><h3 className={`mb-3 text-xs ${narrativeMuted}`}>全书命中 {search.data?.pages[0]?.total ?? 0} 个事件</h3>{search.isPending && <p className="text-xs">正在搜索…</p>}{search.isError && <NarrativeError error={search.error} retry={() => void search.refetch()} />}{matches.map(match => <button key={match.node_id} aria-label={match.title} className={`block w-full border-b py-3 text-left text-xs leading-6 ${narrativeLine}`} onClick={() => select(match.node_id)}><small className={`block ${narrativeMuted}`}>原子事件 · 第 {match.chapter_order} 章</small>{match.title}</button>)}{search.hasNextPage && <button className={control} onClick={() => void search.fetchNextPage()}>更多搜索结果</button>}</div> : initial.arcs.map(arc => <button key={arc.arc_id} className={`block w-full border-t py-3 text-left ${narrativeLine}`} onClick={() => select(`arc:${arc.arc_id}`)}><span className={`text-[11px] ${narrativeMuted}`}>{arc.kind === "main" ? "主线" : "支线"}</span><span className="mt-1 block text-sm leading-6">{arc.title}</span></button>)}
    </aside>
    <div ref={host} aria-label="事件树画布" className="relative min-h-0 min-w-0 flex-1 cursor-grab select-none touch-none overflow-hidden active:cursor-grabbing"
      onPointerDown={event => {
        if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
        // 画布拖拽只平移节点，阻止浏览器建立文字选区，详情和原文仍可复制
        event.preventDefault();
        window.getSelection()?.removeAllRanges();
        setFocusTarget(null);
        drag.current = { x: event.clientX, y: event.clientY, viewX: view.x, viewY: view.y };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={event => { if (drag.current) update({ x: drag.current.viewX + event.clientX - drag.current.x, y: drag.current.viewY + event.clientY - drag.current.y }); }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
      onDragStart={event => event.preventDefault()}>
      <div className="absolute origin-top-left" style={{ width: canvasWidth, height: canvasHeight, transform: `translate(${centeredX + view.x}px, ${centeredY + view.y}px) scale(${scale})` }}>
        <svg className="pointer-events-none absolute inset-0 overflow-visible" width={canvasWidth} height={canvasHeight} role="img" aria-label="以核心问题为中心的全书组织树">
          <desc>连线依据已保存的关系；同一方向的多种关系共用一条线，箭头表示因果、照应或引用方向，空间位置不表示时间</desc>
          <defs><marker id={arrowId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 8 4 L 0 8 Z" className="fill-chart-2" /></marker></defs>
          {[...organizationStems].map(([id, stem]) => <path key={id} data-organization-stem={id} d={stem.trunk} fill="none" stroke="currentColor" className={tones[positions.get(id)!.tone]} strokeOpacity={.45} strokeWidth={1.1} />)}
          {connections.map(edge => {
            const a = positions.get(edge.source_id), b = positions.get(edge.target_id);
            if (!a || !b) return null;
            const structural = edge.kinds.some(kind => kind === "organization" || kind === "local_parent");
            const directed = edge.kinds.some(kind => ["causal", "foreshadowing", "reference"].includes(kind));
            const stem = edge.kinds.every(kind => kind === "organization") ? organizationStems.get(edge.source_id) : undefined;
            const path = stem?.paths.get(edge.target_id) ?? circleConnectionPath(a, b, positions.get("root"));
            const active = edge.source_id === view.selected || edge.target_id === view.selected;
            return <path key={`${edge.source_id}:${edge.target_id}`} data-source-id={edge.source_id} data-target-id={edge.target_id} data-kinds={edge.kinds.join(" ")} d={path} fill="none" stroke="currentColor" className={directed ? "text-chart-2" : tones[b.tone]} strokeOpacity={a.core || active ? .85 : directed ? .28 : .45} strokeWidth={a.core || active ? 1.6 : 1.1} strokeDasharray={structural ? undefined : "4 5"} markerEnd={directed ? `url(#${arrowId})` : undefined}><title>{nodes.get(edge.source_id)?.title} → {nodes.get(edge.target_id)?.title}：{edge.kinds.map(kind => relationLabels[kind]).join("、")}</title></path>;
          })}
        </svg>
        {bookNodes.map(node => {
          const position = positions.get(node.node_id);
          if (!position) return null;
          const arc = initial.arcs.find(arc => arc.arc_id === node.arc_id);
          const isPoint = node.kind === "event", selected = view.selected === node.node_id;
          const circleBox = { left: position.x - position.radius, top: position.y - position.radius, width: position.radius * 2, height: position.radius * 2 };
          const halo = selected ? "ring-2 ring-current ring-offset-4 ring-offset-background shadow-[0_0_0_8px_color-mix(in_srgb,currentColor_10%,transparent)]" : "";
          const title = position.titleBox;
          const selectionBox = title ? { left: Math.min(position.x - 16, title.left), top: title.top, width: Math.max(position.x + 16, title.left + title.width) - Math.min(position.x - 16, title.left), height: title.height } : circleBox;
          const hitSize = Math.max(28, Math.ceil(28 / scale));
          return <article key={node.node_id} data-node-id={node.node_id} data-node-kind={node.kind} data-node-radius={position.radius} data-node-x={position.x} data-node-y={position.y} data-selected={selected} className={`group absolute z-10 ${tones[position.tone]}`} style={{ left: position.left, top: position.top, width: position.width, height: position.height }}>
            {isPoint && title ? <button aria-label={node.title} title={node.title} className="group/selection absolute text-left font-normal outline-none" style={boxStyle(selectionBox, position)} onClick={() => select(node.node_id)}>
              <span data-event-hit-target className="absolute rounded-full" style={{ left: position.x - selectionBox.left - hitSize / 2, top: position.y - selectionBox.top - hitSize / 2, width: hitSize, height: hitSize }} />
              <span data-node-symbol className={`absolute rounded-full bg-current transition-shadow group-focus-visible/selection:ring-2 group-focus-visible/selection:ring-current ${halo}`} style={{ left: circleBox.left - selectionBox.left, top: circleBox.top - selectionBox.top, width: circleBox.width, height: circleBox.height }} />
              <span data-node-title className={`absolute line-clamp-2 text-[13px] leading-5 text-text hover:underline group-focus-visible/selection:underline ${selected ? "font-medium" : ""}`} style={{ left: title.left - selectionBox.left, top: 0, width: title.width }}>{node.title}</span>
            </button> : <button aria-label={node.title} title={node.title} data-node-symbol className={`absolute flex flex-col items-center justify-center rounded-full border ${selected || position.core ? "border-current" : "border-current/60"} bg-background font-normal outline-none transition-shadow hover:bg-surface focus-visible:ring-2 focus-visible:ring-current ${halo} ${node.chapter_id != null && node.chapter_id === view.chapter ? "ring-2 ring-primary" : ""}`} style={boxStyle(circleBox, position)} onClick={() => select(node.node_id)}>
              <span data-node-ring aria-hidden="true" className="pointer-events-none absolute rounded-full border border-current/20" style={{ inset: node.kind === "group" ? 5 : -(position.ringRadius - position.radius) }} />
              {position.core && <span aria-hidden="true" className="absolute -top-[20px] size-1.5 rounded-full bg-current" />}
              {node.kind !== "group" && <small className="mb-2 text-[11px] leading-3 tracking-wide text-text-secondary">{position.core ? "全书 / 核心" : label(node)}</small>}
              <span data-node-title className={`${node.kind === "group" ? "line-clamp-2 w-[54px] text-[13px] leading-[18px]" : position.core ? "line-clamp-3 w-[140px] text-2xl leading-8" : "line-clamp-3 w-[98px] text-lg leading-6"} font-serif text-balance text-center text-text`}>{position.core && bookTitle ? bookTitle : node.title}</span>
              {position.core && bookTitle && <span data-node-context className="mt-2 line-clamp-2 w-[140px] font-serif text-[11px] leading-[18px] text-text-muted">{node.title}</span>}
              {node.kind !== "group" && <small data-node-summary className="mt-2 text-xs leading-4 text-text-secondary">{position.core ? `${initial.arcs.length} 条叙事线 · ${initial.total_events} 个事件` : `${node.child_count} 个直属节点`}</small>}
            </button>}
            {position.metaBox && <small className={`absolute text-[11px] leading-4 text-text-muted ${isPoint ? position.labelSide === "left" ? "text-right" : "text-left" : "text-center"}`} style={boxStyle(position.metaBox, position)}><span className="block truncate">{label(node)}{node.chapter_order ? ` · 正文 ${String(node.chapter_order).padStart(2, "0")}` : ""}</span>{node.kind === "group" && <span className="block">{node.child_count} 个直属事件</span>}</small>}
            {position.descriptionBox && <p data-node-description title={arc?.objective} className="absolute m-0 line-clamp-2 font-serif text-xs leading-[18px] text-text-secondary" style={boxStyle(position.descriptionBox, position)}>{arc?.objective}</p>}
            {position.statusBox && <span className={`absolute text-[11px] leading-4 text-chart-2 ${position.labelSide === "left" ? "text-right" : "text-left"}`} style={boxStyle(position.statusBox, position)}>{node.foreshadowing_status ? foreshadowingLabels[node.foreshadowing_status] : "伏笔已埋设"}</span>}
          </article>;
        })}
      </div>
      <p className={`pointer-events-none absolute bottom-3 right-3 text-[11px] ${narrativeMuted}`}>滚轮缩放 · 拖拽移动</p>
    </div>
    <footer className={`flex shrink-0 flex-wrap items-center justify-between gap-2 border-t py-1 text-xs ${narrativeLine} ${narrativeMuted}`}>
      <div title="大小表示组织层级；主线与支线沿用对应颜色；实线表示组织与父子关系，箭头表示关联方向" className="flex items-center gap-3"><span className="flex items-center gap-1.5"><i className="size-1.5 rounded-full bg-current" />事件</span><span className="flex items-center gap-1.5"><i className="size-2.5 rounded-full border border-current" />事件组</span><span className="flex items-center gap-1.5"><i className="size-3.5 rounded-full border border-current" />叙事线</span><span className="flex items-center gap-1.5"><i className="size-[18px] rounded-full border border-current" />全书</span></div>
      <div className="flex items-center gap-1"><button className={canvasControl} onClick={() => setFocusTarget({ id: "root", overview: true })}>全书中心</button>{view.selected && <button className={canvasControl} onClick={fitBranch}>适应分支</button>}<button aria-label="恢复100%倍率" title="恢复100%倍率" className={`${canvasControl} tabular-nums`} onClick={() => { update({ scale: 1 }); setFocusTarget({ id: view.selected ?? "root" }); }}>{Math.round(scale * 100)}%</button><button aria-label="缩小画布" className={canvasControl} onClick={() => zoom(-.1)}><Minus size={14} /></button><button aria-label="放大画布" className={canvasControl} onClick={() => zoom(.1)}><Plus size={14} /></button><button aria-label="适应全图" className={canvasControl} onClick={fit}><Maximize2 size={14} /></button></div>
    </footer>
    </div>
    {view.selected && <FloatingDetail inline title="节点详情" onClose={() => update({ selected: null, reader: false })}>
      {detail.isPending && <p>正在读取详情…</p>}
      {detail.isError && <><p role="alert">所选节点无法读取</p><button className={control} onClick={() => update({ selected: null, reader: false })}>清除失效选择</button></>}
      {selected && <>
        <nav aria-label="节点归属路径" className={`flex flex-wrap items-center gap-x-2 text-xs ${narrativeMuted}`}>{selected.path.map((item, index) => <span key={item.node_id}>{index > 0 && <span className="mr-2">/</span>}<button title={item.title} className="underline decoration-border underline-offset-4" onClick={() => select(item.node_id)}>{item.kind === "root" ? "全书" : item.kind === "group" ? `事件组 · 第 ${item.chapter_order} 章` : item.kind === "event" ? `${item.chapter_order}章 · ${item.title.slice(0, 10)}${item.title.length > 10 ? "…" : ""}` : item.title}</button></span>)}</nav>
        <h3 className="my-4 text-lg font-medium leading-8">{selected.title}</h3>
        {selected.is_foreshadowing_root && <p className="my-3 text-chart-2">伏笔状态：{selected.foreshadowing_status ? foreshadowingLabels[selected.foreshadowing_status] : "已埋设"}</p>}
        {selected.role && <p className="my-3">{selected.role}</p>}
        {selected.reason && <section className={`my-4 border-l-2 pl-4 ${narrativeLine}`}><h4 className={`text-xs ${narrativeMuted}`}>归属依据</h4><p className="whitespace-pre-line">{selected.reason}</p></section>}
        {selected.participants.length > 0 && <section className="my-4"><h4 className={`text-xs ${narrativeMuted}`}>参与实体</h4>{selected.participants.map((item, index) => <p key={index}>{valueText((item.entity as Record<string, unknown>)?.name ?? item.name)} · {valueText(item.role)}</p>)}</section>}
        {related.length > 0 && <section aria-label="真实关系" className="my-4"><h4 className={`text-xs ${narrativeMuted}`}>真实关系</h4>{related.map(relation => <button key={`${relation.source_id}:${relation.target_id}`} className={`block w-full border-b py-3 text-left ${narrativeLine}`} onClick={() => select(relation.related_node.node_id)}><small className={`block text-xs ${narrativeMuted}`}>{relation.direction === "incoming" ? "来自" : "指向"} · {relation.kinds.map(kind => relationLabels[kind]).join("、")}</small><span className="block text-sm leading-6">{relation.related_node.kind === "group" ? "事件组 · " : ""}{relation.related_node.title}</span></button>)}</section>}
        {selected.references.length > 0 && <section aria-label="跨线引用依据" className="my-4"><h4 className={`text-xs ${narrativeMuted}`}>跨线引用依据</h4>{selected.references.map(reference => <div key={`${reference.arc_id}:${reference.event_id}`} className={`border-b py-3 ${narrativeLine}`}><p className="font-medium">{reference.arc_title}</p><p className={`text-xs ${narrativeMuted}`}>{reference.event_title}</p><p>{reference.role}</p><p>{reference.reason}</p></div>)}</section>}
        {selected.evidence.length > 0 && <button className={`${control} mt-5 flex w-full items-center justify-center gap-2`} onClick={() => update({ reader: true })}><BookOpen size={16} />阅读原文</button>}
      </>}
    </FloatingDetail>}
    {selected && view.reader && <NarrativeReader key={selected.node_id} novelId={novelId} runId={runId} page="event-trees" location={{ ...selected, id: selected.node_id, chapter_id: selected.chapter_id ?? undefined }} onClose={() => update({ reader: false })} />}
  </section>;
}
