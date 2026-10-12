import { useState } from "react";
import { PagedControls } from "@/components/common/PagedControls";
import { useDiagnosisCapacity } from "./useDiagnosisCapacity";
import { cn } from "@/lib/cn";

export interface TopicLabelsProps {
  /** 本轮模型 topic_id 到主题说明的映射 */
  labels?: Record<string, string> | null;
  className?: string;
}

/**
 * 主题标签组件 - 展示小说的主题标签
 */
export function TopicLabels({ labels, className }: TopicLabelsProps) {
  const [page, setPage] = useState(1);
  const { ref, capacity } = useDiagnosisCapacity(36);
  const entries = Object.entries(labels ?? {}).sort(([a], [b]) => Number(a) - Number(b));
  if (entries.length === 0) {
    return (
      <div className={cn("text-sm text-text-muted", className)}>
        暂无主题标签
      </div>
    );
  }
  const pageCount = Math.ceil(entries.length / capacity);
  const currentPage = Math.min(page, pageCount);
  return (
    <div className={cn("flex min-h-0 flex-1 flex-col gap-2", className)} aria-label={`主题标签，共 ${entries.length} 个`}>
      <div ref={ref} className="min-h-0 flex-1">
        {entries.slice((currentPage - 1) * capacity, currentPage * capacity).map(([topicId, label], index) => (
          <div key={topicId} className="flex h-9 items-center gap-3 border-b border-border/50 text-sm">
            <span className="w-6 shrink-0 text-xs tabular-nums text-text-muted">{(currentPage - 1) * capacity + index + 1}</span>
            <span className="truncate text-text" title={label}>{label}</span>
          </div>
        ))}
      </div>
      <div className="h-8 shrink-0"><PagedControls page={currentPage} pageCount={pageCount} onPageChange={setPage} label="主题标签" /></div>
    </div>
  );
}
