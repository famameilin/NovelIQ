import { Badge } from "@/components/ui/badge";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { User, Star, Heart, Zap } from "lucide-react";
import { motion } from "framer-motion";
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
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：将人物页主角卡迁移到共享卡片壳上，统一渐变底、悬停反馈和信息模块层次。
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
    <DashboardCardShell
      title="主角聚焦"
      icon={<User className="h-4 w-4" />}
      accent="primary"
      showOrb
      className={cn(className)}
      bodyClassName="gap-4"
    >
      {hasData ? (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="flex flex-col gap-4"
        >
          <div className="flex items-center gap-4 rounded-2xl border border-border/60 bg-surface/70 p-4">
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
              {protagonist?.dominant_role_function && (
                <p className="text-xs text-text-muted">
                  功能: {protagonist.dominant_role_function}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="flex flex-col items-center rounded-xl border border-border/60 bg-surface/70 p-3">
              <Star className="mb-1 h-4 w-4 text-chart-1" />
              <span className="text-lg font-semibold text-text">
                {protagonist?.appearance_count ?? "—"}
              </span>
              <span className="text-[10px] text-text-muted">出场次数</span>
            </div>

            <div className="flex flex-col items-center rounded-xl border border-border/60 bg-surface/70 p-3">
              <Zap className="mb-1 h-4 w-4 text-chart-2" />
              <span className="text-lg font-semibold text-text">
                {protagonist?.protagonist_score?.toFixed(1) ?? "—"}
              </span>
              <span className="text-[10px] text-text-muted">主角分</span>
            </div>

            <div className="flex flex-col items-center rounded-xl border border-border/60 bg-surface/70 p-3">
              <Heart className="mb-1 h-4 w-4 text-chart-3" />
              <span className="text-lg font-semibold text-text">
                {protagonist?.avg_emotion_score != null
                  ? `${protagonist.avg_emotion_score > 0 ? "+" : ""}${protagonist.avg_emotion_score.toFixed(2)}`
                  : "—"}
              </span>
              <span className="text-[10px] text-text-muted">情绪均值</span>
            </div>
          </div>

          {protagonistArcScore != null && (
            <div className="rounded-2xl border border-border/60 bg-surface/70 px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted">弧线得分:</span>
                <div className="flex items-center gap-1">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <div
                      key={i}
                      className={cn(
                        "h-2 w-2 rounded-full",
                        i < Math.round(protagonistArcScore)
                          ? "bg-primary"
                          : "border border-border"
                      )}
                    />
                  ))}
                  <span className="ml-1 text-xs font-medium text-text">
                    {protagonistArcScore}/10
                  </span>
                </div>
              </div>
            </div>
          )}
        </motion.div>
      ) : (
        <div className="flex h-32 items-center justify-center text-sm text-text-muted">
          暂无主角数据
        </div>
      )}
    </DashboardCardShell>
  );
}
