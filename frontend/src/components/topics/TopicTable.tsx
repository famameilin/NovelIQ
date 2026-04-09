/**
 * TopicTable - 主题详情表格组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-C 主题分布
 * 说明: 可排序的主题详情表格（按 ID/权重），含关键词 Badge 展示和 Framer Motion 进场动画
 */
import { useState, useMemo } from "react";
import { motion } from "framer-motion";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent } from "@/components/ui/card";
import { TopicKeywords } from "./TopicKeywords";
import { cn } from "@/lib/cn";
import type { Topic } from "@/api/types";

export interface TopicTableProps {
  topics: Topic[];
  className?: string;
}

type SortKey = "topic_id" | "weight";
type SortOrder = "asc" | "desc";

export function TopicTable({ topics, className }: TopicTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("weight");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");

  const sortedTopics = useMemo(() => {
    return [...topics].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      return sortOrder === "asc" ? cmp : -cmp;
    });
  }, [topics, sortKey, sortOrder]);

  const handleSort = (key: SortKey) => {
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
    <Card variant="elevated" className={cn("rounded-xl overflow-hidden h-full flex flex-col", className)}>
      <CardContent className="p-0 flex flex-col min-h-0">
        <div className="p-4 border-b border-border">
          <h4 className="text-sm font-semibold text-text">主题详情</h4>
        </div>

        <div className="h-full overflow-auto">
          {hasData ? (
            <Table>
              <TableHeader className="sticky top-0 bg-surface z-10">
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
                    className="cursor-pointer select-none hover:bg-surface-hover text-right"
                    onClick={() => handleSort("weight")}
                    aria-sort={sortKey === "weight" ? (sortOrder === "asc" ? "ascending" : "descending") : undefined}
                  >
                    权重 {renderSortIcon("weight")}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedTopics.map((topic, index) => (
                  <motion.tr
                    key={topic.topic_id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{
                      delay: Math.min(index * 0.03, 0.4), // 限制最大延迟 400ms
                      duration: 0.25,
                    }}
                    className="border-b border-border transition-colors hover:bg-primary-subtle/30"
                  >
                    <TableCell className="font-medium">
                      {topic.label || `主题 ${topic.topic_id + 1}`}
                    </TableCell>
                    <TableCell>
                      <TopicKeywords words={topic.words} maxVisible={5} />
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {(topic.weight * 100).toFixed(1)}%
                    </TableCell>
                  </motion.tr>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="flex h-[200px] items-center justify-center text-sm text-text-muted">
              暂无主题数据
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
