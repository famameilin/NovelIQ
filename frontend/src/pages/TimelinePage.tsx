import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { getTimeline, getTimelineChange } from "@/api/results";
import type { ProgressionDimension, ProgressionTimelineResponse } from "@/api/narrativeTypes";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { FloatingDetail, NarrativeError, NarrativeReader } from "@/components/narrative/NarrativePanels";
import { control, dimensionLabels, dimensionTones, narrativeHeader, narrativeLine, narrativeMuted, narrativePaper, valueText } from "@/components/narrative/presentation";
import { ChapterChanges, ProgressionField, type ChapterChangesSelection } from "@/components/narrative/ProgressionField";
import { useNarrativeState } from "@/components/narrative/useNarrativeState";
import { shouldWriteBackTaskUrl, useNovelScopedTask } from "@/hooks/useNovelScopedTask";

interface ViewState { cutoff: number | null; subject: string; dimension: ProgressionDimension | ""; q: string; window: number; selected: string | null; reader: boolean }

export function TimelinePage() {
  const { novelId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const urlTask = params.get("task_id");
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTask);
  const task = urlTask ?? storeTaskId;
  useEffect(() => {
    if (novelId && shouldWriteBackTaskUrl(urlTask, storeTaskId, urlTaskSyncRef)) navigate(`/novels/${novelId}/timeline?task_id=${storeTaskId}`, { replace: true });
  }, [navigate, novelId, storeTaskId, urlTask, urlTaskSyncRef]);
  const initial = useQuery({ queryKey: ["timeline-access", novelId, task], queryFn: ({ signal }) => getTimeline(novelId!, task!, { signal }), enabled: !!novelId && !!task, retry: false, staleTime: 0, refetchOnMount: "always" });
  return <AnalysisWorkspace title="叙事时间轴" headerClassName={`${narrativeHeader} py-3 [&_h1]:after:-bottom-[13px]`} contentClassName="py-0" className={`${narrativePaper} min-w-[860px] px-7 pb-2 pt-0`}>
    {!task && <p>请先选择分析任务</p>}
    {initial.isPending && task && <p className="p-6 text-sm text-text-muted">正在读取时间轴…</p>}
    {initial.isError && <NarrativeError error={initial.error} retry={() => void initial.refetch()} />}
    {!initial.isError && initial.data && novelId && <TimelineWorkspace key={`${novelId}:${initial.data.run_id}:${params.get("source_fact_id")}:${params.get("through_chapter_id")}`} novelId={novelId} initial={initial.data} sourceFactId={params.get("source_fact_id")} entryChapter={Number(params.get("through_chapter_id")) || null} />}
  </AnalysisWorkspace>;
}

function TimelineWorkspace({ novelId, initial, sourceFactId, entryChapter }: { novelId: string; initial: ProgressionTimelineResponse; sourceFactId: string | null; entryChapter: number | null }) {
  const runId = initial.run_id;
  const [view, update] = useNarrativeState<ViewState>(`${novelId}:${runId}:timeline`, { cutoff: entryChapter ?? initial.through_chapter_id, subject: "", dimension: "", q: "", window: 0, selected: null, reader: false });
  const [chapterGroup, setChapterGroup] = useState<ChapterChangesSelection | null>(null);
  const [stateDimension, setStateDimension] = useState<ProgressionDimension | null>(null);
  const [mappingActive, setMappingActive] = useState(!!sourceFactId);
  const [entryActive, setEntryActive] = useState(entryChapter != null);
  const cutoff = entryActive && entryChapter ? entryChapter : view.cutoff ?? initial.through_chapter_id;
  const cutoffIndex = Math.max(0, initial.chapters.findIndex(chapter => chapter.chapter_id === cutoff));
  // 已读未读区分已删：变化清单与分布覆盖全书，截点只决定"当前局面"状态行与阅读原文的口径
  const lastChapterId = initial.chapters.at(-1)?.chapter_id;
  const query = useInfiniteQuery({
    queryKey: ["progression", novelId, runId, view.subject, view.dimension, view.q, mappingActive ? sourceFactId : null],
    queryFn: ({ pageParam, signal }) => getTimeline(novelId, runId, { throughChapterId: lastChapterId, subjectId: mappingActive ? undefined : view.subject || undefined, dimension: mappingActive ? undefined : view.dimension || undefined, q: mappingActive ? "" : view.q, sourceFactId: mappingActive ? sourceFactId ?? undefined : undefined, cursor: pageParam, limit: 80, signal }),
    initialPageParam: undefined as string | undefined, getNextPageParam: page => page.next_cursor ?? undefined,
    retry: false, staleTime: 0,
  });
  const data = query.data?.pages[0];
  const changes = query.data?.pages.flatMap(page => page.changes) ?? [];
  const selectedId = mappingActive ? changes[0]?.progression_change_id : view.selected;
  const detail = useQuery({ queryKey: ["progression-detail", novelId, runId, selectedId], queryFn: ({ signal }) => getTimelineChange(novelId, runId, selectedId!, lastChapterId!, signal), enabled: !!selectedId && lastChapterId != null && !query.isError, retry: false, staleTime: 0 });
  const statesQuery = useQuery({ queryKey: ["progression-states", novelId, runId, cutoff], queryFn: ({ signal }) => getTimeline(novelId, runId, { throughChapterId: cutoff ?? undefined, limit: 1, signal }), enabled: cutoff != null, retry: false, staleTime: 0 });
  const chapters = data?.chapters ?? initial.chapters;
  const dimensions = Object.keys(dimensionLabels) as ProgressionDimension[];
  const states = statesQuery.data?.states.filter(state => mappingActive || ((!view.subject || state.subject_id === view.subject) && (!view.dimension || state.dimension === view.dimension))) ?? [];
  const stateDimensions = dimensions.filter(dimension => states.some(state => state.dimension === dimension));
  useEffect(() => {
    if (entryActive && entryChapter) update({ cutoff: entryChapter, selected: null, reader: false });
  }, [entryActive, entryChapter, update]);
  function selectChapter(index: number) {
    setMappingActive(false); setEntryActive(false); setChapterGroup(null); setStateDimension(null);
    update({ cutoff: chapters[Math.max(0, Math.min(chapters.length - 1, index))]?.chapter_id ?? null, selected: null, reader: false });
  }
  function filter(patch: Partial<ViewState>) { setChapterGroup(null); setStateDimension(null); setMappingActive(false); setEntryActive(false); update({ ...patch, cutoff, selected: null, reader: false }); }
  // 搜索框 300ms 防抖：全书扫描是时间轴最重的请求，逐键触发会形成请求风暴
  const [qDraft, setQDraft] = useState<string | null>(null);
  useEffect(() => {
    if (qDraft == null) return;
    const timer = setTimeout(() => {
      setQDraft(null);
      setChapterGroup(null); setStateDimension(null); setMappingActive(false); setEntryActive(false);
      update({ q: qDraft, cutoff, selected: null, reader: false });
    }, 300);
    return () => clearTimeout(timer);
  }, [qDraft, cutoff, update]);
  const selected = detail.data;
  if (query.isError) return <NarrativeError error={query.error} retry={() => void query.refetch()} />;
  function selectChange(id: string) {
    setMappingActive(false); setEntryActive(false); setChapterGroup(null); setStateDimension(null);
    update({ cutoff, selected: id, reader: false });
  }
  function showStates(dimension: ProgressionDimension) {
    setMappingActive(false); setEntryActive(false); setChapterGroup(null);
    update({ cutoff, selected: null, reader: false }); setStateDimension(dimension);
  }
  return <section aria-label="连续叙事时间轴" className="relative flex min-h-0 min-w-0 flex-1 flex-col">
    <div className="flex h-14 shrink-0 items-center justify-between gap-5">
      <div><p className={`text-[11px] ${narrativeMuted}`}>NARRATIVE PROGRESSION / 叙事动态</p><h2 className="mt-1 text-[23px] font-normal">第 {cutoffIndex + 1} 章 · 当前局面</h2></div>
      <span aria-hidden="true" className="shrink-0 font-serif text-[48px] leading-none tracking-[-3px]">{String(cutoffIndex + 1).padStart(2, "0")}</span>
    </div>
    <div aria-label="截点已知状态" className={`grid h-[104px] shrink-0 gap-7 ${stateDimensions.length === 4 ? "grid-cols-4" : stateDimensions.length === 3 ? "grid-cols-3" : "grid-cols-2"}`}>
      {stateDimensions.map(dimension => {
        const known = states.filter(state => state.dimension === dimension).sort((a, b) => b.chapter_order - a.chapter_order || a.subject_id.localeCompare(b.subject_id));
        const latest = known[0];
        return <section key={dimension} className={`min-w-0 border-t-2 pt-2 ${narrativeLine}`}>
          <h3 className={`text-[11px] leading-[14px] ${narrativeMuted}`}>{dimensionLabels[dimension]}</h3>
          <button className="mt-1 block w-full truncate text-left text-[13px] font-medium leading-[18px]" title={latest.subject_title} onClick={() => showStates(dimension)}>{latest.subject_title}</button>
          <p className="mt-0.5 line-clamp-2 text-[12px] leading-[18px]" title={valueText(latest.state)}>{valueText(latest.state)}</p>
          <div className={`mt-0.5 flex items-center justify-between gap-2 text-[10px] leading-3 ${narrativeMuted}`}><span>最近变化 · 第 {String(latest.chapter_order).padStart(2, "0")} 章</span><button aria-label={`查看${dimensionLabels[dimension]}全部主体`} className="shrink-0 hover:underline" onClick={() => showStates(dimension)}>{known.length > 1 ? `其余 ${known.length - 1} 个主体` : "查看状态"}</button></div>
        </section>;
      })}
      {!stateDimensions.length && <p className={`self-center text-sm ${narrativeMuted}`}>截至本章尚无已记录状态</p>}
    </div>
    <div className="flex h-9 shrink-0 items-center justify-between gap-3">
      <h2 className={`flex items-center gap-2 text-[11px] ${narrativeMuted}`}><i className="size-1.5 rounded-full bg-primary" />CHANGE HISTORY / 变化记录</h2>
      <div className={`flex border-b text-xs ${narrativeLine}`}><button aria-pressed={!view.dimension} className="px-3 py-2 aria-pressed:shadow-[inset_0_-2px_var(--color-primary)]" onClick={() => filter({ dimension: "" })}>全部变化</button><button aria-pressed={view.dimension === "foreshadowing"} className="px-3 py-2 aria-pressed:shadow-[inset_0_-2px_var(--color-primary)]" onClick={() => filter({ dimension: "foreshadowing" })}>伏笔变化</button></div>
    </div>
    <div className="flex h-11 shrink-0 items-center gap-3">
      <label className={`flex w-48 min-w-32 shrink items-center gap-2 border-b py-2 ${narrativeLine} ${narrativeMuted}`}><Search size={14} /><input aria-label="搜索全部变化" placeholder="查找全书情节与变化" className="min-w-0 flex-1 bg-transparent text-xs text-inherit outline-none" value={qDraft ?? view.q} onChange={event => setQDraft(event.target.value)} /></label>
      <select aria-label="变化主体" className={`${control} w-40 shrink-0`} value={view.subject} onChange={event => filter({ subject: event.target.value })}><option value="">全部主体</option>{data?.subjects.map(subject => <option key={`${subject.dimension}:${subject.subject_id}`} value={subject.subject_id}>{subject.subject_title}</option>)}</select>
      <select aria-label="变化维度" className={`${control} w-28 shrink-0`} value={view.dimension} onChange={event => filter({ dimension: event.target.value as ViewState["dimension"] })}><option value="">全部维度</option>{dimensions.map(dimension => <option value={dimension} key={dimension}>{dimensionLabels[dimension]}</option>)}</select>
      <select aria-label="显示窗口" className={`${control} w-28 shrink-0`} value={view.window} onChange={event => filter({ window: Number(event.target.value) })}><option value={0}>全书坐标</option><option value={8}>最近八章</option><option value={4}>最近四章</option></select>
      <div className="ml-auto flex min-w-0 items-center gap-1"><button aria-label="上一章" className={`${control} border-0 px-1`} disabled={!cutoffIndex} onClick={() => selectChapter(cutoffIndex - 1)}><ChevronLeft size={14} /></button><select aria-label="阅读截点" value={cutoff ?? ""} className={`${control} w-40`} onChange={event => selectChapter(chapters.findIndex(chapter => chapter.chapter_id === Number(event.target.value)))}>{chapters.map(chapter => <option key={chapter.chapter_id} value={chapter.chapter_id}>{chapter.order}. {chapter.title}</option>)}</select><button aria-label="下一章" className={`${control} border-0 px-1`} disabled={cutoffIndex >= chapters.length - 1} onClick={() => selectChapter(cutoffIndex + 1)}><ChevronRight size={14} /></button></div>
    </div>
    {mappingActive && <p role="status" className={`shrink-0 pb-2 text-xs ${narrativeMuted}`}>{query.isPending ? "正在定位来源事实…" : changes.length ? "已定位来源事实对应的变化" : "该图谱事实没有对应的时间轴变化"}<button className="ml-3 underline" onClick={() => { setMappingActive(false); setEntryActive(false); update({ cutoff }); }}>显示全部变化</button></p>}
    <ProgressionField chapters={chapters} cutoffIndex={cutoffIndex} changes={changes} distribution={data?.distribution ?? []} dimension={mappingActive ? "" : view.dimension} windowSize={view.window} focusChapterId={mappingActive ? changes[0]?.chapter_id : undefined} selectedId={selectedId} onChapter={selectChapter} onSelect={selectChange} onWindowChange={window => filter({ window })} onGroup={group => { setMappingActive(false); setEntryActive(false); setStateDimension(null); update({ cutoff, selected: null, reader: false }); setChapterGroup(group); }} />
    <footer className={`flex h-9 shrink-0 items-center justify-between gap-3 text-[11px] ${narrativeMuted}`}><span role="status">{query.isPending ? "正在读取变化…" : !data?.total ? "没有符合条件的变化" : `${data.total} 条已发生的变化 · ${data.subjects.length} 个主体`}</span>{query.hasNextPage ? <button className="underline underline-offset-4 disabled:opacity-40" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>继续加载变化（已显示 {changes.length} / {data?.total}）</button> : <span>同章记录并列 · 点击展开详情</span>}</footer>
    {stateDimension && <FloatingDetail title={`${dimensionLabels[stateDimension]} · 当前状态`} onClose={() => setStateDimension(null)}>{states.filter(state => state.dimension === stateDimension).sort((a, b) => b.chapter_order - a.chapter_order || a.subject_id.localeCompare(b.subject_id)).map(state => <article key={state.subject_id} className={`border-b py-4 first:pt-0 ${narrativeLine}`}><h3 className="text-sm font-medium">{state.subject_title}</h3><p className="my-2 break-words text-[13px] leading-6">{valueText(state.state)}</p><p className={`text-[11px] ${narrativeMuted}`}>最近变化 · 第 {state.chapter_order} 章</p></article>)}</FloatingDetail>}
    {chapterGroup && <ChapterChanges novelId={novelId} runId={runId} group={chapterGroup} subject={view.subject} q={view.q} onClose={() => setChapterGroup(null)} onSelect={selectChange} />}
    {selectedId && <FloatingDetail title="变化详情" onClose={() => { setMappingActive(false); update({ selected: null, reader: false }); }}>
      {detail.isPending && <p>正在读取详情…</p>}{detail.isError && <><p role="alert">当前截点无法读取这条变化，已保留阅读位置。</p><button className={control} onClick={() => { setMappingActive(false); update({ selected: null, reader: false }); }}>清除失效选择</button></>}
      {selected && <><span className={dimensionTones[selected.dimension]}>{dimensionLabels[selected.dimension]} · 第 {selected.chapter_order} 章</span><h3 className="my-4 text-lg font-medium leading-8">{selected.title}</h3><p className={narrativeMuted}>{selected.subject_title}</p><div className={`my-5 border-y py-4 ${narrativeLine}`}><p className={`text-xs ${narrativeMuted}`}>变化前</p><p>{valueText(selected.before)}</p><p className={`mt-4 text-xs ${narrativeMuted}`}>变化后</p><p>{valueText(selected.after)}</p></div><p className={`text-xs ${narrativeMuted}`}>{selected.evidence_scope === "paragraph" ? "段落级依据" : "章节级依据"}</p><button className={`${control} mt-4 flex w-full items-center justify-center gap-2`} onClick={() => update({ reader: true })}><BookOpen size={16} />阅读原文</button></>}
    </FloatingDetail>}
    {selected && view.reader && <NarrativeReader key={selected.progression_change_id} novelId={novelId} runId={runId} page="timeline" throughChapterId={lastChapterId} location={{ ...selected, id: selected.progression_change_id }} onClose={() => update({ reader: false })} />}
  </section>;
}
