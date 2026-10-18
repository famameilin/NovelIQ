/**
 * TopicKeywordsCard - TextRank 关键词卡片
 *
 * 口径独立于 LDA 主题词：独立词共现图（窗口 5）+ PageRank 的 Top-N。
 */
import { Hash } from "lucide-react";

import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import type { KeywordScoreItem } from "@/api/types";
import { cn } from "@/lib/cn";

interface TopicKeywordsCardProps {
  keywords: KeywordScoreItem[];
  unavailableReason?: string | null;
  className?: string;
  columns?: 1 | 2;
}

export function TopicKeywordsCard({ keywords, unavailableReason, className, columns = 1 }: TopicKeywordsCardProps) {
  const maxScore = keywords.length > 0 ? Math.max(...keywords.map((keyword) => keyword.score)) : 0;

  return (
    <DashboardCardShell
      title="全书关键词"
      icon={<Hash className="h-4 w-4" />}
      accent="chart-3"
      className={className}
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1"
    >
      {keywords.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-muted">
          {unavailableReason ? "当前任务暂时无法生成全书关键词" : "暂无可用关键词"}
        </p>
      ) : (
        <ul className={cn("grid min-h-0 flex-1 auto-rows-fr gap-x-4 gap-y-1", columns === 2 && "grid-cols-2")}>
          {keywords.map((keyword) => (
            <li key={keyword.word} className="flex min-h-0 items-center gap-2">
              <span className="w-20 shrink-0 truncate text-sm text-text" title={keyword.word}>{keyword.word}</span>
              <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover">
                <div
                  className="h-full rounded-full bg-chart-3"
                  style={{ width: `${maxScore > 0 ? (keyword.score / maxScore) * 100 : 0}%` }}
                />
              </div>
              <span className="w-14 shrink-0 text-right text-xs text-text-muted">
                {keyword.score.toFixed(4)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </DashboardCardShell>
  );
}
