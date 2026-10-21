import { useEffect, useRef, useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronLeft, ChevronRight, X } from "lucide-react";
import { getNarrativeSource } from "@/api/results";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus, isRunRequiresRebuildError } from "@/api/errorGuards";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { control, narrativeLine, narrativeMuted, narrativePaper } from "./presentation";
import { useNarrativeState } from "./useNarrativeState";

export function NarrativeError({ error, retry }: { error: unknown; retry: () => void }) {
  if (isAnalysisNotCompleteError(error)) return <AnalysisNotCompleteState description="任务完成后才能查看结果。" failed={getAnalysisNotCompleteRunStatus(error) === "failed"} />;
  if (isRunRequiresRebuildError(error)) return <p role="alert" className="p-6 text-sm text-text-muted">该任务的事件树需要从原文重建，请选择按新版契约生成的任务。</p>;
  return <div role="alert" className={`border p-6 text-sm ${narrativeLine}`}>加载失败，请重试。<button className={`${control} ml-4`} onClick={retry}>重试</button></div>;
}

export function FloatingDetail({ title, children, onClose, inline = false }: { title: string; children: ReactNode; onClose: () => void; inline?: boolean }) {
  useEffect(() => {
    // 原文模态窗打开时只处理最上层的 Esc，保留下面的详情与选中节点
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape" && !event.defaultPrevented && !document.querySelector('[role="dialog"][aria-modal="true"]')) onClose(); };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [onClose]);
  const panel = <aside role="dialog" aria-label={title} className={`${inline ? "relative h-full min-h-0 border-l" : "fixed bottom-5 right-5 top-20 z-30 border shadow-xl"} flex w-[370px] flex-col overflow-hidden bg-surface text-text ${narrativeLine}`}>
    <header className={`flex items-center justify-between border-b p-5 ${narrativeLine}`}><h2 className={`text-xs font-medium ${narrativeMuted}`}>{title}</h2><button className="p-2 hover:bg-surface-hover" aria-label={`关闭${title}`} onClick={onClose}><X size={18} /></button></header>
    <div className="min-h-0 flex-1 overflow-y-auto p-5 text-sm leading-7">{children}</div>
  </aside>;
  return inline ? panel : createPortal(panel, document.body);
}

type EvidenceLocation = { id: string; kind?: "event"; evidence_scope: "chapter" | "paragraph"; anchor_paragraph_ids: number[]; chapter_id?: number; evidence: Array<Record<string, unknown>> };
export function NarrativeReader({ novelId, runId, page, location, throughChapterId, onClose }: { novelId: string; runId: string; page: "timeline" | "event-trees"; location: EvidenceLocation; throughChapterId?: number; onClose: () => void }) {
  const [opener] = useState(() => document.activeElement as HTMLElement | null);
  const reader = useRef<HTMLDivElement>(null);
  const ids = [...new Set(location.evidence.map(item => Number(item.chapter_id)).filter(Number.isFinite))];
  const [chapter, setChapter] = useState(location.chapter_id ?? ids[0]);
  const [position, updatePosition] = useNarrativeState<{ paragraph: number | null; start: number }>(`${novelId}:${runId}:${page}:reader:${location.id}:${chapter}`, { paragraph: null, start: 0 });
  const [offset, setOffset] = useState<number | null>(null);
  const [anchor, setAnchor] = useState(location.anchor_paragraph_ids[0]);
  const chapterAnchors = location.evidence.filter(item => Number(item.chapter_id) === chapter).map(item => Number(item.paragraph_id)).filter(id => Number.isFinite(id) && location.anchor_paragraph_ids.includes(id));
  const source = useQuery({ queryKey: [page, "source", novelId, runId, location.kind, location.id, chapter, throughChapterId], queryFn: ({ signal }) => getNarrativeSource(novelId, runId, { page, id: location.id, kind: location.kind, chapterId: chapter, throughChapterId }, signal), retry: false, staleTime: 0 });
  // 段落较长时在阅读层分片，段落身份不变，选锚点直接落到相应纸页
  const fragments = source.data?.paragraphs.flatMap(paragraph => {
    const items = [];
    for (let start = 0; start < paragraph.text.length; start += 650) items.push({ ...paragraph, start, text: paragraph.text.slice(start, start + 650) });
    return items;
  }) ?? [];
  const target = position.paragraph ?? (location.evidence_scope === "paragraph" ? anchor : null);
  const initial = Math.max(0, fragments.findIndex(item => item.paragraph_id === target && item.start === position.start));
  const current = Math.min(offset ?? initial, Math.max(0, fragments.length - 1));
  function move(index: number) { setOffset(index); updatePosition({ paragraph: fragments[index]?.paragraph_id ?? null, start: fragments[index]?.start ?? 0 }); }
  return <Dialog.Root open onOpenChange={open => { if (!open) onClose(); }}><Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-50 bg-background/85 backdrop-blur-sm" />
    <Dialog.Content ref={reader} className="fixed inset-8 z-50 flex items-center justify-center outline-none" aria-modal="true" aria-label="章节原文" aria-labelledby={undefined} aria-describedby={undefined}
      onEscapeKeyDown={event => event.stopPropagation()}
      onCloseAutoFocus={event => { event.preventDefault(); if (opener?.isConnected) opener.focus(); }}>
    <section className={`flex h-full w-full max-w-4xl flex-col border shadow-xl ${narrativePaper} ${narrativeLine}`}>
      <header className={`flex items-center justify-between gap-3 border-b p-5 ${narrativeLine}`}><div><span className={`flex items-center gap-2 text-xs ${narrativeMuted}`}><BookOpen size={15} />原文证据</span><Dialog.Title className="mt-2 font-serif text-xl">{source.data?.title ?? "正在读取…"}</Dialog.Title></div><Dialog.Close asChild><button aria-label="关闭原文" className={control}><X size={18} /></button></Dialog.Close></header>
      <div className={`flex flex-wrap gap-3 px-6 pt-4 text-xs ${narrativeMuted}`}><span>{location.evidence_scope === "paragraph" ? "段落级依据" : "章节级依据，不标记具体段落"}</span>{ids.length > 1 && <select aria-label="证据章节" className={control} value={chapter} onChange={event => { const id = Number(event.target.value); setChapter(id); setAnchor(Number(location.evidence.find(item => Number(item.chapter_id) === id)?.paragraph_id)); setOffset(null); }}>{ids.map(id => <option key={id} value={id}>章节 {id}</option>)}</select>}{location.evidence_scope === "paragraph" && chapterAnchors.length > 1 && <select aria-label="证据锚点" className={control} value={anchor} onChange={event => { const id = Number(event.target.value); setAnchor(id); move(Math.max(0, fragments.findIndex(item => item.paragraph_id === id))); }}>{chapterAnchors.map(id => <option key={id} value={id}>段落 {id}</option>)}</select>}</div>
      <div className="min-h-0 flex-1 overflow-y-auto px-14 py-8">{source.isPending && <p>正在读取原文…</p>}{source.isError && <NarrativeError error={source.error} retry={() => void source.refetch()} />}{fragments[current] && <p className={`whitespace-pre-wrap p-4 font-serif text-lg leading-10 ${location.evidence_scope === "paragraph" && location.anchor_paragraph_ids.includes(fragments[current].paragraph_id) ? "border-l-2 border-primary bg-surface-hover" : ""}`}>{fragments[current].text}</p>}</div>
      <footer className={`flex items-center justify-between border-t p-5 ${narrativeLine}`}><button aria-label="上一页原文" className={control} disabled={current === 0} onClick={() => move(current - 1)}><ChevronLeft size={18} /></button><span className={`text-xs ${narrativeMuted}`}>{fragments.length ? current + 1 : 0} / {fragments.length}</span><button aria-label="下一页原文" className={control} disabled={current >= fragments.length - 1} onClick={() => move(current + 1)}><ChevronRight size={18} /></button></footer>
    </section>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>;
}
