import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Search } from "lucide-react";
import { getTimelineSubjects } from "@/api/results";
import type { PlotlineDimension } from "@/api/narrativeTypes";
import { control, narrativeLine, narrativeMuted } from "@/components/narrative/presentation";

interface SubjectPickerProps {
  novelId: string;
  taskId: string;
  throughChapterId: number | null;
  dimension: PlotlineDimension | "";
  value: string;
  selectedTitle: string;
  onChange: (subjectId: string, subjectTitle: string) => void;
}

/** 主体按名称在后端搜索，避免一次下载全书主体 */
export function SubjectPicker({ novelId, taskId, throughChapterId, dimension, value, selectedTitle, onChange }: SubjectPickerProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [term, setTerm] = useState("");
  useEffect(() => {
    if (!draft) {
      setTerm("");
      return;
    }
    const timer = setTimeout(() => setTerm(draft), 250);
    return () => clearTimeout(timer);
  }, [draft]);
  const query = useQuery({
    queryKey: ["timeline-subjects", novelId, taskId, throughChapterId, dimension, term],
    queryFn: ({ signal }) => getTimelineSubjects(novelId, taskId, { throughChapterId: throughChapterId ?? undefined, dimension: dimension || undefined, q: term, limit: 30, signal }),
    enabled: open && throughChapterId != null,
    retry: false,
    staleTime: 30_000,
  });
  const subjects = query.data?.subjects ?? [];
  function choose(subjectId: string, subjectTitle: string) {
    setOpen(false);
    setDraft("");
    onChange(subjectId, subjectTitle);
  }
  return <div className="relative w-40 shrink-0">
    <button type="button" aria-label="变化主体" aria-expanded={open} onClick={() => setOpen(current => !current)} className={`${control} flex w-full items-center justify-between gap-2`}>
      <span className="truncate">{value ? selectedTitle || "已选主体" : "全部主体"}</span>
      <ChevronDown size={14} className="shrink-0" />
    </button>
    {open && <>
      <div className="fixed inset-0 z-30" aria-hidden="true" onClick={() => setOpen(false)} />
      <div className={`absolute left-0 top-full z-40 mt-1 w-64 border bg-surface p-2 shadow-lg ${narrativeLine}`}>
        <label className={`flex items-center gap-2 border-b py-1 ${narrativeLine} ${narrativeMuted}`}>
          <Search size={14} />
          <input autoFocus aria-label="搜索变化主体" placeholder="搜索主体名称" className="min-w-0 flex-1 bg-transparent text-xs text-inherit outline-none" value={draft} onChange={event => setDraft(event.target.value)} />
        </label>
        <div className="mt-1 max-h-64 overflow-y-auto">
          <button type="button" className="block w-full truncate px-2 py-1.5 text-left text-xs hover:bg-surface-hover" onClick={() => choose("", "")}>全部主体</button>
          {subjects.map(subject => <button key={`${subject.dimension}:${subject.subject_id}`} type="button" className="block w-full truncate px-2 py-1.5 text-left text-xs hover:bg-surface-hover" onClick={() => choose(subject.subject_id, subject.subject_title)}>{subject.subject_title}</button>)}
          {!subjects.length && <p className={`px-2 py-2 text-xs ${narrativeMuted}`}>{query.isPending ? "正在读取主体…" : "没有匹配的主体"}</p>}
        </div>
        {query.data && query.data.total > subjects.length && <p className={`mt-1 px-2 text-[11px] ${narrativeMuted}`}>共 {query.data.total} 个主体，输入名称缩小范围</p>}
      </div>
    </>}
  </div>;
}
