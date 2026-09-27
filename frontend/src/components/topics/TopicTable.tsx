/**
 * TopicTable - 主题详情表格组件
 *
 * 可排序的主题详情表格（按 ID/权重），含关键词 Badge 展示
 */
import { useState, useMemo } from "react";
import { Table2 } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { PagedControls } from "@/components/common/PagedControls";
import { cn } from "@/lib/cn";
import { TopicKeywords } from "./TopicKeywords";
import type { Topic } from "@/api/types";

export interface TopicTableProps {
  topics: Topic[];
  className?: string;
}

type SortKey = "topic_id" | "weight";
type SortOrder = "asc" | "desc";
const PAGE_SIZE = 5;

export function TopicTable({ topics, className }: TopicTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("weight");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [page, setPage] = useState(1);

  const sortedTopics = useMemo(() => {
    return [...topics].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      return sortOrder === "asc" ? cmp : -cmp;
    });
  }, [topics, sortKey, sortOrder]);
  const pageCount = Math.ceil(sortedTopics.length / PAGE_SIZE);
  const currentPage = Math.min(page, Math.max(pageCount, 1));
  const visibleTopics = sortedTopics.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const handleSort = (key: SortKey) => {
    setPage(1);
    if (sortKey === key) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortOrder("desc");
    }
  };

  const renderSortIcon = (columnKey: SortKey) => {
    if (sortKey !== columnKey) {
      return <span className="ml-1 text-text-muted/50">↕</span>;
    }
    return (
      <span className="ml-1 text-primary">
        {sortOrder === "asc" ? "↑" : "↓"}
      </span>
    );
  };

  const hasData = topics.length > 0;

  return (
    <DashboardCardShell
      title="主题详情"
      icon={<Table2 className="h-4 w-4" />}
      accent="chart-4"
      className={cn("h-full min-h-0", className)}
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1 gap-2"
    >
      <div className="min-h-0 flex-1 rounded-2xl border border-border/70 bg-surface/70 [&>div]:h-full">
        {hasData ? (
          <Table className="h-full">
            <TableHeader className="bg-surface">
              <TableRow>
                <TableHead
                  className="cursor-pointer select-none hover:bg-surface-hover"
                  onClick={() => handleSort("topic_id")}
                  aria-sort={sortKey === "topic_id" ? (sortOrder === "asc" ? "ascending" : "descending") : undefined}
                >
                  主题 {renderSortIcon("topic_id")}
                </TableHead>
                <TableHead>关键词</TableHead>
                <TableHead
                  className="cursor-pointer select-none text-right hover:bg-surface-hover"
                  onClick={() => handleSort("weight")}
                  aria-sort={sortKey === "weight" ? (sortOrder === "asc" ? "ascending" : "descending") : undefined}
                >
                  权重 {renderSortIcon("weight")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleTopics.map((topic) => (
                <TableRow key={topic.topic_id}>
                  <TableCell className="py-2 font-medium">
                    {topic.label || `主题 ${topic.topic_id + 1}`}
                  </TableCell>
                  <TableCell className="py-2">
                    <TopicKeywords words={topic.words} maxVisible={3} />
                  </TableCell>
                  <TableCell className="py-2 text-right font-mono text-sm">
                    {(topic.weight * 100).toFixed(1)}%
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="flex h-[200px] items-center justify-center text-sm text-text-muted">
            暂无主题数据
          </div>
        )}
      </div>
      <PagedControls page={currentPage} pageCount={pageCount} onPageChange={setPage} label="主题清单" />
    </DashboardCardShell>
  );
}
