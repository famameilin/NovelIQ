import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { User, Star, Heart, Zap } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Character } from "@/api/types";

export interface ProtagonistCardProps {
  /** 主角角色数据 */
  protagonist?: Character | null;
  /** 主角名称（备用） */
  protagonistName?: string | null;
  /** 弧线得分 */
  arcScores?: Record<string, number> | null;
  className?: string;
}

/**
 * 主角聚焦卡片 - 突出展示主角信息
 */
export function ProtagonistCard({
  protagonist,
  protagonistName,
  arcScores,
  className,
}: ProtagonistCardProps) {
  const name = protagonist?.name || protagonistName;
  const hasData = name;

  // 获取主角的弧线得分
  const protagonistArcScore = name && arcScores ? arcScores[name] : null;

  return (
    <Card variant="elevated" className={cn("rounded-xl overflow-hidden", className)}>
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex items-center gap-2">
          <User className="h-4 w-4 text-primary" />
          <h4 className="text-sm font-semibold text-text">主角聚焦</h4>
        </div>

        {hasData ? (
          <div className="flex flex-col gap-4">
            {/* 主角头像占位 + 名称 */}
            <div className="flex items-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
                <User className="h-8 w-8 text-primary" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-lg font-semibold text-text">{name}</span>
                  <Badge variant="secondary" className="text-[10px]">
                    主角
                  </Badge>
                </div>
                {protagonist?.dominant_function && (
                  <p className="text-xs text-text-muted">
                    功能: {protagonist.dominant_function}
                  </p>
                )}
              </div>
            </div>

            {/* 主角数据 */}
            <div className="grid grid-cols-3 gap-3">
              <div className="flex flex-col items-center rounded-lg bg-surface-hover p-3">
                <Star className="mb-1 h-4 w-4 text-chart-1" />
                <span className="text-lg font-semibold text-text">
                  {protagonist?.count ?? "—"}
                </span>
                <span className="text-[10px] text-text-muted">出场次数</span>
              </div>

              <div className="flex flex-col items-center rounded-lg bg-surface-hover p-3">
                <Zap className="mb-1 h-4 w-4 text-chart-2" />
                <span className="text-lg font-semibold text-text">
                  {protagonist?.protagonist_score?.toFixed(1) ?? "—"}
                </span>
                <span className="text-[10px] text-text-muted">主角分</span>
              </div>

              <div className="flex flex-col items-center rounded-lg bg-surface-hover p-3">
                <Heart className="mb-1 h-4 w-4 text-chart-3" />
                <span className="text-lg font-semibold text-text">
                  {protagonist?.avg_sentiment != null
                    ? `${protagonist.avg_sentiment > 0 ? "+" : ""}${protagonist.avg_sentiment.toFixed(2)}`
                    : "—"}
                </span>
                <span className="text-[10px] text-text-muted">情绪均值</span>
              </div>
            </div>

            {/* 弧线得分 */}
            {protagonistArcScore != null && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted">弧线得分:</span>
                <div className="flex items-center gap-1">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div
                      key={i}
                      className={cn(
                        "h-2 w-2 rounded-full",
                        i < protagonistArcScore
                          ? "bg-primary"
                          : "border border-border"
                      )}
                    />
                  ))}
                  <span className="ml-1 text-xs font-medium text-text">
                    {protagonistArcScore}/5
                  </span>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex h-32 items-center justify-center text-sm text-text-muted">
            暂无主角数据
          </div>
        )}
      </CardContent>
    </Card>
  );
}