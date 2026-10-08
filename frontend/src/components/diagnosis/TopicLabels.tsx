import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { PagedControls } from "@/components/common/PagedControls";
import { useCompactAnalysisViewport } from "@/hooks/useCompactAnalysisViewport";
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
  const compact = useCompactAnalysisViewport();
  const entries = Object.entries(labels ?? {}).sort(([a], [b]) => Number(a) - Number(b));
  if (entries.length === 0) {
    return (
      <div className={cn("text-sm text-text-muted", className)}>
        暂无主题标签
      </div>
    );
  }
  const pageCount = compact ? Math.ceil(entries.length / 8) : 1;
  const currentPage = Math.min(page, pageCount);
  const visibleEntries = compact ? entries.slice((currentPage - 1) * 8, currentPage * 8) : entries;
  return (
    <div className={cn("flex flex-col gap-2", className)} aria-label={`主题标签，共 ${entries.length} 个`}>
      <div className="grid grid-cols-3 gap-1.5 xl:grid-cols-4">
        {visibleEntries.map(([topicId, label]) => (
          <Badge key={topicId} variant="secondary" className="justify-center px-1.5 py-1 text-center text-[10px] leading-4">
            {label}
          </Badge>
        ))}
      </div>
      <PagedControls page={currentPage} pageCount={pageCount} onPageChange={setPage} label="主题标签" />
    </div>
  );
}
