import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BookOpen, ChevronLeft, ChevronRight, RefreshCw, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { getEventSourceChapter } from "@/api/results";
import type { EventForestNode, EventSourceChapterResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface EventSourceReaderProps {
  novelId: string;
  taskId: string;
  node: EventForestNode;
  onClose: () => void;
}

type SourceParagraph = EventSourceChapterResponse["paragraphs"][number];
type PageFragment = Pick<SourceParagraph, "paragraph_id"> & { text: string; continued: boolean };

/** 按阅读层的可用字数分成纸页；超长段落分片但保留原段落身份 */
function paginateParagraphs(paragraphs: SourceParagraph[], capacity: number): PageFragment[][] {
  const pages: PageFragment[][] = [];
  let page: PageFragment[] = [];
  let used = 0;
  for (const paragraph of paragraphs) {
    const text = paragraph.text.trim();
    if (!text) continue;
    let offset = 0;
    while (offset < text.length) {
      const room = capacity - used - (page.length > 0 ? 22 : 0);
      if (room < Math.min(100, capacity / 3) && page.length > 0) {
        pages.push(page);
        page = [];
        used = 0;
        continue;
      }
      const end = Math.min(text.length, offset + Math.max(1, capacity - used));
      page.push({ paragraph_id: paragraph.paragraph_id, text: text.slice(offset, end), continued: offset > 0 });
      used += end - offset + 22;
      offset = end;
      if (used >= capacity && offset < text.length) {
        pages.push(page);
        page = [];
        used = 0;
      }
    }
  }
  if (page.length > 0) pages.push(page);
  return pages.length > 0 ? pages : [[]];
}

/** 原文独立占用视口，翻页不会改变事件林的尺寸或滚动位置 */
export function EventSourceReader({ novelId, taskId, node, onClose }: EventSourceReaderProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [viewport, setViewport] = useState(() => ({ width: window.innerWidth, height: window.innerHeight }));
  const sourceQuery = useQuery({
    queryKey: ["event-source", novelId, taskId, node.chapter_id],
    queryFn: () => getEventSourceChapter(novelId, taskId, node.chapter_id),
    staleTime: 5 * 60 * 1000,
  });
  const capacity = Math.max(260, Math.min(900,
    Math.floor((viewport.width - 440) / 18) * Math.floor((viewport.height - 370) / 30) * .85,
  ));
  const pages = useMemo(
    () => paginateParagraphs(sourceQuery.data?.paragraphs ?? [], Math.floor(capacity)),
    [capacity, sourceQuery.data],
  );
  const currentPage = Math.min(pageIndex, pages.length - 1);
  const preciseIds = new Set(node.evidence_scope === "paragraph" ? node.anchor_paragraph_ids : []);

  useEffect(() => {
    closeRef.current?.focus();
    const resize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowRight") setPageIndex((index) => Math.min(index + 1, pages.length - 1));
      if (event.key === "ArrowLeft") setPageIndex((index) => Math.max(index - 1, 0));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, pages.length]);

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label="章节原文" className="fixed inset-0 z-50 flex items-center justify-center bg-[#281e1c]/75 p-4 md:p-8">
      <div className="flex h-full w-full max-w-[1160px] flex-col rounded-[28px] border border-[#e4c8b9] bg-[#fbf6ef] shadow-2xl">
        <header className="flex shrink-0 items-center justify-between gap-4 border-b border-[#e8d4c7] px-6 py-4 md:px-9">
          <div className="min-w-0">
            <span className="flex items-center gap-2 text-xs font-semibold tracking-[.18em] text-[#a16453]"><BookOpen className="h-4 w-4" />章节手稿 · 第 {node.chapter_order} 章</span>
            <h2 className="mt-1 truncate font-serif text-xl font-semibold text-[#49332e]">{sourceQuery.data?.title ?? "正在读取原文…"}</h2>
          </div>
          <Button ref={closeRef} variant="ghost" size="sm" onClick={onClose} aria-label="关闭原文"><X className="h-5 w-5" /></Button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col px-6 py-4 md:px-12 md:py-6">
          <div className="mb-4 shrink-0 text-xs leading-5 text-[#80665c]">
            {node.evidence_scope === "chapter"
              ? "本节点只有章节级依据。可阅读整章，未定位到具体段落。"
              : "已用浅色标出精确段落依据。"}
          </div>
          {sourceQuery.isLoading && <p className="text-sm text-[#80665c]">正在读取原文…</p>}
          {sourceQuery.isError && (
            <div className="flex items-center gap-3 text-sm text-[#80665c]">
              <span>原文加载失败</span>
              <Button variant="outline" size="sm" onClick={() => void sourceQuery.refetch()}><RefreshCw className="mr-1 h-4 w-4" />重试</Button>
            </div>
          )}
          {sourceQuery.data && (
            <article aria-label="本页原文" className="min-h-0 flex-1 space-y-4 border-y border-[#e9d8cc] px-2 py-5 font-serif text-[15px] leading-8 text-[#493b34] md:px-5">
              {pages[currentPage].map((paragraph, index) => (
                <p
                  key={`${paragraph.paragraph_id}-${index}`}
                  data-paragraph-id={paragraph.paragraph_id}
                  className={cn("whitespace-pre-wrap break-words", !paragraph.continued && "indent-8", preciseIds.has(paragraph.paragraph_id) && "rounded-lg bg-primary/10 px-3 py-1")}
                >{paragraph.text}</p>
              ))}
            </article>
          )}
        </div>
        <footer className="flex shrink-0 items-center justify-between gap-3 px-6 pb-5 md:px-12">
          <Button variant="outline" size="sm" disabled={!sourceQuery.data || currentPage === 0} onClick={() => setPageIndex((index) => index - 1)}><ChevronLeft className="mr-1 h-4 w-4" />上一页</Button>
          <span className="text-xs tabular-nums text-[#80665c]">{sourceQuery.data ? `${currentPage + 1} / ${pages.length}` : "—"}</span>
          <Button variant="outline" size="sm" disabled={!sourceQuery.data || currentPage >= pages.length - 1} onClick={() => setPageIndex((index) => index + 1)}>下一页<ChevronRight className="ml-1 h-4 w-4" /></Button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
