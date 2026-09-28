import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";

import { getEventForest } from "@/api/results";
import { getAnalysisNotCompleteRunStatus, isAnalysisNotCompleteError } from "@/api/errorGuards";
import type { EventForestNode, EventForestResponse, EventForestTree } from "@/api/types";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { shouldWriteBackTaskUrl, useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { EventSourceReader } from "@/pages/eventTrees/EventSourceReader";
import { EventTreeInspector } from "@/pages/eventTrees/EventTreeInspector";
import { GrowthForestCanvas } from "@/pages/eventTrees/GrowthForestCanvas";
import { GrowthTreeCanvas } from "@/pages/eventTrees/GrowthTreeCanvas";
import { buildEventTreeUrl } from "@/pages/eventTrees/eventTreeNavigation";
import { treeNodeIds } from "@/pages/eventTrees/eventTreeLayout";

const STALE_TIME = 5 * 60 * 1000;

/** 章节、关键词和结构筛选只改变森林中可见的树，不修改原始因果数据 */
function filterTrees(
  forest: EventForestResponse,
  nodes: Map<string, EventForestNode>,
  chapter: string,
  query: string,
  foreshadow: string,
  branchOnly: boolean,
): EventForestTree[] {
  const foreshadowIds = new Set(forest.foreshadowing_edges.map((edge) => edge.tree_id));
  const needle = query.trim().toLocaleLowerCase();
  return forest.event_trees.filter((tree) => {
    const root = nodes.get(tree.root_event_id);
    if (!root) return false;
    // 跨章树在章节筛选中只计入根节点所在的锚定章
    if (chapter !== "all" && String(root.chapter_order) !== chapter) return false;
    if (foreshadow === "foreshadow" && !foreshadowIds.has(tree.tree_id)) return false;
    if (foreshadow === "ordinary" && foreshadowIds.has(tree.tree_id)) return false;
    if (branchOnly && !tree.secondary_groups.some((group) => group.branch.length > 0)) return false;
    if (needle && !treeNodeIds(tree).some((id) => nodes.get(id)?.description.toLocaleLowerCase().includes(needle))) return false;
    return true;
  }).sort((a, b) => {
    const rootA = nodes.get(a.root_event_id)!;
    const rootB = nodes.get(b.root_event_id)!;
    return rootA.chapter_order - rootB.chapter_order || rootA.char_start - rootB.char_start;
  });
}

export function EventTreesPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const urlTaskId = searchParams.get("task_id");
  const urlTreeId = searchParams.get("tree_id");
  const urlEventId = searchParams.get("event_id");
  const urlChapter = searchParams.get("chapter");
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTaskId);
  const taskId = urlTaskId ?? storeTaskId;
  const chapterFilter = urlChapter && /^\d+$/.test(urlChapter) ? urlChapter : "all";
  const chapterOrder = chapterFilter === "all" ? null : Number(chapterFilter);
  const [query, setQuery] = useState("");
  const [foreshadowFilter, setForeshadowFilter] = useState("all");
  const [branchOnly, setBranchOnly] = useState(false);
  const [readerNodeId, setReaderNodeId] = useState<string | null>(null);

  useEffect(() => {
    if (novelId && storeTaskId && shouldWriteBackTaskUrl(urlTaskId, storeTaskId, urlTaskSyncRef)) {
      // 首次补 task_id 时保留树/节点深链；任务切换时清除旧任务的定位
      const keepLocation = !urlTaskId;
      navigate(buildEventTreeUrl(novelId, storeTaskId, {
        treeId: keepLocation ? urlTreeId : null,
        eventId: keepLocation ? urlEventId : null,
        chapterOrder: keepLocation ? chapterOrder : null,
      }), { replace: true });
    }
  }, [navigate, novelId, storeTaskId, urlTaskId, urlTaskSyncRef, urlTreeId, urlEventId, chapterOrder]);

  const forestQuery = useQuery<EventForestResponse>({
    queryKey: ["event-forest", novelId, taskId],
    queryFn: () => getEventForest(novelId!, taskId!),
    enabled: Boolean(novelId && taskId),
    staleTime: STALE_TIME,
  });
  const forest = forestQuery.data;
  const nodes = useMemo(() => new Map((forest?.event_nodes ?? []).map((node) => [node.event_id, node])), [forest]);
  const chapters = useMemo(() => {
    // 按章节深链进入零树章节时，筛选器仍显示该章并给出空状态
    const lastOrder = Math.max(forest?.visible_through_chapter_order ?? 0, ...((forest?.event_nodes ?? []).map((node) => node.chapter_order)));
    return Array.from({ length: lastOrder }, (_, index) => index + 1);
  }, [forest]);
  const coveredChapterCount = useMemo(() => new Set((forest?.event_nodes ?? []).map((node) => node.chapter_order)).size, [forest]);
  const visibleTrees = useMemo(() => forest
    ? filterTrees(forest, nodes, chapterFilter, query, foreshadowFilter, branchOnly)
    : [], [forest, nodes, chapterFilter, query, foreshadowFilter, branchOnly]);
  const foreshadowByTree = useMemo(
    () => new Map((forest?.foreshadowing_edges ?? []).map((edge) => [edge.tree_id, edge])),
    [forest],
  );

  // 无 tree_id 的默认画面是整片林子；只给 event_id 的深链也能精确进入该树
  const linkedTreeId = urlEventId ? nodes.get(urlEventId)?.tree_id : null;
  const selectedTree = (urlTreeId || linkedTreeId)
    ? forest?.event_trees.find((tree) => tree.tree_id === urlTreeId)
      ?? forest?.event_trees.find((tree) => tree.tree_id === linkedTreeId)
      ?? null
    : null;
  const selectedNode = selectedTree
    ? nodes.get(urlEventId ?? "")?.tree_id === selectedTree.tree_id
      ? nodes.get(urlEventId ?? "") ?? nodes.get(selectedTree.root_event_id)
      : nodes.get(selectedTree.root_event_id)
    : null;
  const foreshadow = selectedTree ? foreshadowByTree.get(selectedTree.tree_id) ?? null : null;
  const relatedCausal = (forest?.causal_edges ?? []).filter((edge) => {
    const sourceTreeId = nodes.get(edge.source_event_id)?.tree_id;
    const targetTreeId = nodes.get(edge.target_event_id)?.tree_id;
    return Boolean(selectedTree && sourceTreeId && targetTreeId && sourceTreeId !== targetTreeId
      && (sourceTreeId === selectedTree.tree_id || targetTreeId === selectedTree.tree_id));
  });

  function selectTree(tree: EventForestTree, eventId = tree.root_event_id) {
    if (!novelId || !taskId) return;
    setReaderNodeId(null);
    navigate(buildEventTreeUrl(novelId, taskId, { treeId: tree.tree_id, eventId, chapterOrder }));
  }

  function selectEvent(eventId: string) {
    if (!novelId || !taskId || !selectedTree) return;
    setReaderNodeId(null);
    navigate(buildEventTreeUrl(novelId, taskId, { treeId: selectedTree.tree_id, eventId, chapterOrder }), { replace: true });
  }

  function selectRelatedEvent(eventId: string) {
    const relatedTree = forest?.event_trees.find((tree) => tree.tree_id === nodes.get(eventId)?.tree_id);
    if (relatedTree) selectTree(relatedTree, eventId);
  }

  function returnToForest() {
    if (!novelId || !taskId) return;
    setReaderNodeId(null);
    navigate(buildEventTreeUrl(novelId, taskId, { chapterOrder }));
  }

  const isAnalysisNotComplete = isAnalysisNotCompleteError(forestQuery.error);
  const failed = getAnalysisNotCompleteRunStatus(forestQuery.error) === "failed";

  if (!novelId) return <AnalysisWorkspace title="事件树"><p>小说不存在</p></AnalysisWorkspace>;
  if (!taskId) return <AnalysisWorkspace title="事件树"><p className="text-sm text-text-muted">请先选择分析任务</p></AnalysisWorkspace>;

  return (
    <AnalysisWorkspace title="事件树" headerClassName="mb-2">
      {forestQuery.isLoading && <p className="rounded-xl border border-border/70 p-6 text-sm text-text-muted">正在读取事件树…</p>}
      {isAnalysisNotComplete && (
        <AnalysisNotCompleteState
          title={failed ? "事件树分析任务已失败" : "事件树结果尚未完成"}
          description={failed ? "请重新发起分析后查看事件树。" : "当前任务仍在分析中，请等待完成。"}
          failed={failed}
        />
      )}
      {forestQuery.isError && !isAnalysisNotComplete && (
        <div className="flex items-center gap-3 rounded-xl border border-border/70 p-6 text-sm text-text-muted">
          <span>事件树加载失败</span>
          <Button variant="outline" size="sm" onClick={() => void forestQuery.refetch()}><RefreshCw className="mr-1 h-4 w-4" />重试</Button>
        </div>
      )}
      {forest && forest.event_trees.length === 0 && <p className="rounded-xl border border-border/70 p-6 text-sm text-text-muted">当前任务暂无事件树</p>}
      {forest && forest.event_trees.length > 0 && (
        <div className="flex min-h-0 flex-1 flex-col gap-2 pb-2">
          <dl className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1 border-b border-border/60 px-1 pb-2 text-xs" aria-label="事件树摘要">
            {[
              ["覆盖章节", coveredChapterCount], ["事件树", forest.event_trees.length],
              ["事件节点", forest.event_nodes.length],
              ["次因旁支", forest.event_nodes.filter((node) => node.cause_role === "secondary").length],
              ["伏笔树", foreshadowByTree.size],
            ].map(([label, value]) => <div key={label} className="flex items-baseline gap-1.5"><dt className="text-text-muted">{label}</dt><dd className="font-semibold tabular-nums text-text">{value}</dd></div>)}
          </dl>

          {!selectedTree && (
            <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-surface/70 px-3 py-2" aria-label="事件树筛选">
              <label className="text-xs text-text-muted">章节 <select value={chapters.some((chapter) => String(chapter) === chapterFilter) ? chapterFilter : "all"} onChange={(event) => {
                if (novelId && taskId) navigate(buildEventTreeUrl(novelId, taskId, { chapterOrder: event.target.value === "all" ? null : Number(event.target.value) }), { replace: true });
              }} className="ml-1 h-8 rounded-md border border-border bg-background px-2 text-sm text-text">
                <option value="all">全部章节</option>{chapters.map((chapter) => <option key={chapter} value={chapter}>第 {chapter} 章</option>)}
              </select></label>
              <label className="relative min-w-[170px] flex-1 text-xs text-text-muted"><span className="sr-only">关键词</span><Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索事件描述" className="h-8 pl-8" /></label>
              <label className="text-xs text-text-muted">伏笔 <select value={foreshadowFilter} onChange={(event) => setForeshadowFilter(event.target.value)} className="ml-1 h-8 rounded-md border border-border bg-background px-2 text-sm text-text">
                <option value="all">全部事件树</option><option value="foreshadow">只看伏笔</option><option value="ordinary">只看普通事件</option>
              </select></label>
              <label className="flex items-center gap-1.5 text-xs text-text"><input type="checkbox" checked={branchOnly} onChange={(event) => setBranchOnly(event.target.checked)} />只看含旁支</label>
              <span className="ml-auto text-xs tabular-nums text-text-muted">显示 {visibleTrees.length} 棵</span>
            </div>
          )}

          {!selectedTree && (visibleTrees.length === 0
            ? <p className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-border/70 text-sm text-text-muted">当前筛选下没有事件树</p>
            : <GrowthForestCanvas forest={forest} trees={visibleTrees} nodes={nodes} onOpenTree={selectTree} focusChapterOrder={chapterOrder} />)}

          {selectedTree && selectedNode && (
            <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-[minmax(0,1fr)_310px]">
              <GrowthTreeCanvas
                tree={selectedTree}
                nodes={nodes}
                selectedEventId={selectedNode.event_id}
                foreshadowStatus={foreshadow?.status}
                onSelectEvent={selectEvent}
                onBack={returnToForest}
              />
              <EventTreeInspector
                node={selectedNode}
                foreshadow={foreshadow}
                causalEdges={relatedCausal}
                nodes={nodes}
                onReadSource={() => setReaderNodeId(selectedNode.event_id)}
                onSelectRelatedEvent={selectRelatedEvent}
              />
            </div>
          )}
        </div>
      )}
      {forest && novelId && taskId && selectedNode && readerNodeId === selectedNode.event_id && (
        <EventSourceReader novelId={novelId} taskId={taskId} node={selectedNode} onClose={() => setReaderNodeId(null)} />
      )}
    </AnalysisWorkspace>
  );
}
