import { useRef, useState } from "react";
import { ChevronLeft, ChevronRight, LocateFixed } from "lucide-react";
import { useInfiniteQuery } from "@tanstack/react-query";
import type { NarrativeChapter, ProgressionChange, ProgressionDimension, ProgressionTimelineResponse } from "@/api/narrativeTypes";
import { getTimeline } from "@/api/results";
import { FloatingDetail, NarrativeError } from "./NarrativePanels";
import { control, dimensionLabels, dimensionTones, narrativeLine, narrativeMuted } from "./presentation";
import { useNarrativeSize } from "./useNarrativeSize";

const allDimensions = Object.keys(dimensionLabels) as ProgressionDimension[];
export interface ChapterChangesSelection { chapterId: number; chapterOrder: number; dimension: ProgressionDimension }

/** 固定视口内按章节定位，浏览窗口和阅读截点分别维护，同章记录按完整分布聚合 */
export function ProgressionField({ chapters, cutoffIndex, changes, distribution, selectedId, dimension = "", windowSize = 4, focusChapterId, onChapter, onSelect, onGroup, onWindowChange }: {
  chapters: NarrativeChapter[];
  cutoffIndex: number;
  changes: ProgressionChange[];
  distribution: ProgressionTimelineResponse["distribution"];
  selectedId: string | null | undefined;
  dimension?: ProgressionDimension | "";
  windowSize?: number;
  focusChapterId?: number;
  onChapter: (order: number) => void;
  onSelect: (id: string) => void;
  onGroup: (group: ChapterChangesSelection) => void;
  onWindowChange?: (size: number) => void;
}) {
  const [host, size] = useNarrativeSize();
  const [viewport, setViewport] = useState<{ focusId: number | undefined; windowSize: number; start: number } | null>(null);
  const drag = useRef<{ x: number; start: number } | null>(null);
  const focusIndex = Math.max(0, focusChapterId == null ? cutoffIndex : chapters.findIndex(chapter => chapter.chapter_id === focusChapterId));
  const focusId = chapters[focusIndex]?.chapter_id;
  // 全书坐标一屏最多 20 章，超出部分用箭头或拖动平移，避免长篇把轨道挤压到不可点击
  const count = Math.min(Math.max(1, windowSize || 20), Math.max(1, chapters.length));
  const lastStart = Math.max(0, chapters.length - count);
  const defaultStart = Math.max(0, Math.min(lastStart, focusIndex - count + 1));
  const start = viewport?.focusId === focusId && viewport.windowSize === windowSize ? Math.max(0, Math.min(lastStart, viewport.start)) : defaultStart;
  const visible = chapters.slice(start, start + count);
  const dimensions = dimension ? [dimension] : allDimensions;
  const plotWidth = Math.max(1, size.width - 80);
  const bodyHeight = Math.max(1, size.height - 64);
  const laneHeight = bodyHeight / dimensions.length;
  const step = plotWidth / count;
  const compact = step < 122;
  // 全书总览按画布空间合并相邻章节，避免长篇小说产生重叠或无法点击的微小节点
  const bucketSize = compact ? Math.max(1, Math.ceil(44 / step)) : 1;
  const tickStride = Math.max(1, Math.ceil(36 / step));
  const indices = new Map(visible.map((chapter, index) => [chapter.chapter_id, index]));
  const points = distribution.filter(point => indices.has(point.chapter_id));
  const pan = (nextStart: number) => setViewport({ focusId, windowSize, start: Math.max(0, Math.min(lastStart, nextStart)) });
  const activate = (point: ProgressionTimelineResponse["distribution"][number]) => {
    const change = changes.find(item => item.chapter_id === point.chapter_id && item.dimension === point.dimension);
    if (point.count === 1 && change) onSelect(change.progression_change_id);
    else onGroup({ chapterId: point.chapter_id, chapterOrder: point.chapter_order, dimension: point.dimension });
  };
  return <div ref={host} className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden" aria-label="章节变化轨道">
    <div className={`flex h-8 shrink-0 items-center border-b ${narrativeLine}`}>
      <div className={`flex w-20 shrink-0 items-center text-[11px] ${narrativeMuted}`}>章节</div>
      {chapters.length > count && <button aria-label="向前翻页章节" className={`shrink-0 p-1 disabled:opacity-30 ${narrativeMuted}`} disabled={start <= 0} onClick={() => pan(start - Math.max(1, count - 1))}><ChevronLeft size={13} /></button>}
      <div className="relative min-w-0 flex-1 self-stretch">
        {visible.map((chapter, index) => (chapter.chapter_id === chapters[cutoffIndex]?.chapter_id || (index % tickStride === 0 && Math.abs(start + index - cutoffIndex) * step >= 32)) && <button key={chapter.chapter_id} aria-label={`阅读至第 ${chapter.order} 章`} aria-pressed={chapter.chapter_id === chapters[cutoffIndex]?.chapter_id} title={chapter.title} onClick={() => onChapter(start + index)} className={`absolute top-0.5 flex h-7 -translate-x-1/2 items-center px-2 font-mono text-[11px] ${narrativeMuted} aria-pressed:bg-text aria-pressed:text-background`} style={{ left: `${(index + .5) * 100 / count}%` }}>{String(chapter.order).padStart(2, "0")}</button>)}
      </div>
      {chapters.length > count && <button aria-label="向后翻页章节" className={`shrink-0 p-1 disabled:opacity-30 ${narrativeMuted}`} disabled={start >= lastStart} onClick={() => pan(start + Math.max(1, count - 1))}><ChevronRight size={13} /></button>}
    </div>
    <div className="flex min-h-0 flex-1">
      <aside className={`flex w-20 shrink-0 flex-col text-[11px] ${narrativeMuted}`}>
        {dimensions.map(lane => <div key={lane} className="relative min-h-0 flex-1"><span className="absolute bottom-[10px] left-1">{dimensionLabels[lane]}</span></div>)}
      </aside>
      {/* 两侧占位与刻度行翻页箭头同宽，保证刻度数字与轨道列对齐 */}
      {chapters.length > count && <div aria-hidden="true" className="w-[21px] shrink-0" />}
      <div aria-label="变化清单" className="relative flex min-h-0 min-w-0 flex-1 touch-none select-none flex-col" onPointerDown={event => {
        if (chapters.length <= count || (event.target as Element).closest("button")) return;
        drag.current = { x: event.clientX, start };
        event.currentTarget.setPointerCapture(event.pointerId);
      }} onPointerMove={event => {
        if (drag.current) pan(drag.current.start + Math.round((drag.current.x - event.clientX) / step));
      }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
        <svg width="100%" height="100%" className="pointer-events-none absolute inset-0" viewBox={`0 0 ${plotWidth} ${bodyHeight}`} preserveAspectRatio="none" role="img" aria-label="按正文顺序排列的四维变化轨道">
          {visible.filter((_, index) => index % tickStride === 0).map(chapter => <path key={chapter.chapter_id} d={`M ${(indices.get(chapter.chapter_id)! + .5) * step} 0 V ${bodyHeight}`} className="stroke-border/50" strokeDasharray="2 5" />)}
        </svg>
        {dimensions.map(lane => {
          const records = points.filter(point => point.dimension === lane);
          const buckets = new Map<number, typeof records>();
          for (const point of records) {
            const bucket = Math.floor(indices.get(point.chapter_id)! / bucketSize);
            buckets.set(bucket, [...(buckets.get(bucket) ?? []), point]);
          }
          const labelHeight = laneHeight >= 80 ? 54 : 18;
          const labelWidth = Math.min(200, compact ? 148 : step - 16);
          const labels = new Map<number, number>();
          const candidates = [...buckets.keys()].sort((a, b) => {
            // 标签布局只随窗口与选中态变化，不随截点变化：同一窗口呈现同一张画布
            const priority = (bucket: number) => {
              const group = buckets.get(bucket)!;
              return changes.some(item => item.progression_change_id === selectedId && item.dimension === lane && group.some(record => record.chapter_id === item.chapter_id)) ? 0 : 1;
            };
            return priority(a) - priority(b) || b - a;
          });
          // 标题仍就地附着于节点，密集总览只避让文字，所有节点和完整计数始终保留
          for (const bucket of candidates) {
            const first = bucket * bucketSize, last = Math.min(count, first + bucketSize);
            const center = (first + last) * step / 2;
            const left = Math.max(0, Math.min(plotWidth - labelWidth, center - labelWidth / 2));
            if (!compact || [...labels.values()].every(other => left + labelWidth + 12 <= other || other + labelWidth + 12 <= left)) labels.set(bucket, left);
          }
          const firstIndex = records.length ? Math.min(...records.map(point => indices.get(point.chapter_id)!)) : null;
          return <div key={lane} data-dimension={lane} className="relative min-h-0 flex-1">
            <div aria-hidden="true" className="absolute inset-x-0 bottom-4 h-px bg-border" />
            {firstIndex != null && <div aria-hidden="true" className={`absolute bottom-4 h-px bg-current ${dimensionTones[lane]}`} style={{ left: `${(firstIndex + .5) * 100 / count}%`, width: `${100 - (firstIndex + .5) * 100 / count}%` }} />}
            {[...buckets].map(([bucket, group]) => {
              const first = bucket * bucketSize, last = Math.min(count, first + bucketSize);
              const point = group[0];
              const nodeWidth = compact ? Math.max(24, Math.min(36, step * (last - first) - 8)) : labelWidth;
              const centerX = Math.max(nodeWidth / 2, Math.min(plotWidth - nodeWidth / 2, (first + last) * step / 2));
              const center = centerX * 100 / plotWidth;
              const total = group.reduce((sum, item) => sum + item.count, 0);
              const change = changes.find(item => item.chapter_id === point.chapter_id && item.dimension === lane);
              const groupedChapters = bucketSize > 1;
              const title = groupedChapters ? `第 ${visible[first].order}–${visible[last - 1].order} 章` : change?.title ?? `${total} 条变化`;
              const label = groupedChapters ? `细览${title} · ${total} 条变化` : `${String(point.chapter_order).padStart(2, "0")} / ${dimensionLabels[lane]} ${title}${total > 1 ? ` 共 ${total} 条 · 展开` : ""}`;
              const active = changes.some(item => item.progression_change_id === selectedId && item.dimension === lane && group.some(record => record.chapter_id === item.chapter_id));
              const labelLeft = labels.get(bucket);
              return <button key={bucket} data-testid="timeline-change-node" data-count={total} aria-label={label} aria-pressed={active} title={groupedChapters ? `${title} · ${total} 条变化，点击细览` : `${change?.subject_title ?? dimensionLabels[lane]}\n${title}`} onClick={() => {
                  if (groupedChapters && onWindowChange) {
                    onWindowChange(4);
                    setViewport({ focusId, windowSize: 4, start: Math.min(Math.max(0, chapters.length - 4), start + first) });
                  } else activate(point);
                }} className="group absolute bottom-0 z-20 -translate-x-1/2 text-left text-text focus-visible:outline-2 focus-visible:outline-current focus-visible:outline-offset-2" style={{ left: `${center}%`, height: Math.min(laneHeight, labelHeight + 24), width: nodeWidth }}>
                  {labelLeft != null && <span data-testid="timeline-node-label" className="absolute bottom-6 text-left" style={{ left: labelLeft - center * plotWidth / 100 + nodeWidth / 2, width: labelWidth, height: labelHeight }}>
                    {labelHeight > 18 && <small className={`flex justify-between gap-2 text-[10px] leading-[14px] ${narrativeMuted}`}><span>{change?.action === "setup" ? "埋设" : change?.action === "reinforce" ? "强化" : change?.action === "payoff" ? "疑似回收" : `第 ${point.chapter_order} 章`}</span><span className="shrink-0">{total > 1 ? `${total} 条 ↗` : "查看 ↗"}</span></small>}
                    <strong className={`${labelHeight > 18 ? "mt-1 line-clamp-2" : "block truncate"} text-[12px] font-normal leading-[18px] group-hover:underline group-hover:underline-offset-4 group-aria-pressed:underline group-aria-pressed:underline-offset-4`}>{title}</strong>
                  </span>}
                  <span aria-hidden="true" className={`pointer-events-none absolute bottom-[13px] left-1/2 size-1.5 -translate-x-1/2 bg-current group-hover:ring-4 group-hover:ring-current/15 group-aria-pressed:ring-4 group-aria-pressed:ring-current/25 ${dimensionTones[lane]} ${lane === "plot" || lane === "character" ? "rounded-full" : lane === "foreshadowing" ? "rotate-45" : ""}`} />
                  <span className={`absolute inset-x-0 bottom-0 text-center font-mono text-[10px] leading-3 ${narrativeMuted}`}>{total > 1 ? total : ""}</span>
              </button>;
            })}
            {!records.length && <p className={`absolute inset-0 flex items-center justify-center text-[11px] ${narrativeMuted}`}>本段暂无符合条件的变化</p>}
          </div>;
        })}
      </div>
      {chapters.length > count && <div aria-hidden="true" className="w-[21px] shrink-0" />}
    </div>
    <div className={`flex h-8 shrink-0 items-center justify-between border-t px-1 text-[11px] ${narrativeLine} ${narrativeMuted}`}>
      <span aria-live="polite">{visible.length ? `当前显示第 ${visible[0].order}–${visible.at(-1)!.order} 章` : "暂无章节"} · {compact ? "点击节点展开" : "拖动轨道浏览章节"}</span>
      <div className="flex items-center gap-3"><button aria-label="向前浏览章节" className="p-1 disabled:opacity-30" disabled={!start} onClick={() => pan(start - Math.max(1, count - 1))}><ChevronLeft size={14} /></button><button aria-label="定位阅读章节" className="inline-flex items-center gap-1 hover:text-primary" onClick={() => pan(Math.max(0, Math.min(lastStart, cutoffIndex - count + 1)))}><LocateFixed size={13} />定位阅读章节</button><button aria-label="向后浏览章节" className="p-1 disabled:opacity-30" disabled={start >= lastStart} onClick={() => pan(start + Math.max(1, count - 1))}><ChevronRight size={14} /></button></div>
    </div>
  </div>;
}

/** 密集章节单独分页，图上的聚合数量来自完整分布，不能受已加载页数限制 */
export function ChapterChanges({ novelId, runId, group, subject, q, onClose, onSelect }: {
  novelId: string; runId: string; group: ChapterChangesSelection; subject: string; q: string;
  onClose: () => void; onSelect: (id: string) => void;
}) {
  const query = useInfiniteQuery({
    queryKey: ["progression-chapter", novelId, runId, group.chapterId, group.dimension, subject, q],
    queryFn: ({ pageParam, signal }) => getTimeline(novelId, runId, { throughChapterId: group.chapterId, windowStartChapterId: group.chapterId, dimension: group.dimension, subjectId: subject || undefined, q, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined, getNextPageParam: page => page.next_cursor ?? undefined, retry: false,
  });
  return <FloatingDetail title="本章变化" onClose={onClose}><p className={`text-xs ${narrativeMuted}`}>第 {group.chapterOrder} 章 · {dimensionLabels[group.dimension]} · {query.data?.pages[0]?.total ?? 0} 条</p>{query.isPending && <p>正在读取变化…</p>}{query.isError && <NarrativeError error={query.error} retry={() => void query.refetch()} />}{query.data?.pages.flatMap(page => page.changes).map(change => <button key={change.progression_change_id} className={`mt-4 block w-full border-t pt-4 text-left ${narrativeLine}`} onClick={() => onSelect(change.progression_change_id)}><small className={narrativeMuted}>{change.subject_title}</small><span className="block">{change.title}</span></button>)}{query.hasNextPage && <button className={`${control} mt-4 w-full`} disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>继续加载本章变化</button>}</FloatingDetail>;
}
