/**
 * TopicKeywordsCard - TextRank 关键词卡片（赛道 A3）
 *
 * 口径独立于 LDA 主题词：独立词共现图（窗口 5）+ PageRank 的 Top-N。
 */
import { Hash } from "lucide-react";

import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import type { KeywordScoreItem } from "@/api/types";

interface TopicKeywordsCardProps {
  keywords: KeywordScoreItem[];
  unavailableReason?: string | null;
  className?: string;
}

export function TopicKeywordsCard({ keywords, unavailableReason, className }: TopicKeywordsCardProps) {
  const maxScore = keywords.length > 0 ? Math.max(...keywords.map((keyword) => keyword.score)) : 0;

  return (
    <DashboardCardShell
      title="TextRank 关键词"
      icon={<Hash className="h-4 w-4" />}
      accent="chart-3"
      className={className}
      bodyClassName="min-h-0 overflow-y-auto"
    >
      {keywords.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-muted">
          {unavailableReason ?? "暂无可建图的词元"}
        </p>
      ) : (
        <ul className="space-y-2">
          {keywords.map((keyword) => (
            <li key={keyword.word} className="flex items-center gap-3">
              <span className="w-24 shrink-0 truncate text-sm text-text">{keyword.word}</span>
              <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover">
                <div
                  className="h-full rounded-full bg-chart-3"
                  style={{ width: `${maxScore > 0 ? (keyword.score / maxScore) * 100 : 0}%` }}
                />
              </div>
              <span className="w-16 shrink-0 text-right text-xs text-text-muted">
                {keyword.score.toFixed(4)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </DashboardCardShell>
  );
}
