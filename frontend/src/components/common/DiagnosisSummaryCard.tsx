import { User, Target, Sparkles, ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DashboardCardShell,
  getMetricAccentHoverTextClass,
} from "@/components/common/DashboardCardShell";
import { cn } from "@/lib/cn";
import { hasCompleteFocusContract } from "@/lib/diagnosisContract";
import type { DiagnosisResult } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface DiagnosisSummaryCardProps {
  diagnosis: DiagnosisResult;
  novelId: string;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：让诊断画像卡回收到共享卡片壳上，复用 MetricCard 的视觉原语而不是继续使用普通 Card
 *
 * 2026-04-27，任务：protagonist-focus-contract
 * 修改原因：诊断摘要不再展示唯一主角，而是展示焦点结构与焦点人物列表
 */
export function DiagnosisSummaryCard({
  diagnosis,
  novelId,
  className,
}: DiagnosisSummaryCardProps) {
  const navigate = useNavigate();
  const hasFocusContract = hasCompleteFocusContract(diagnosis);
  const focusStructureLabel =
    diagnosis.focus_structure === "dual"
      ? "双主角"
      : diagnosis.focus_structure === "ensemble"
      ? "群像焦点"
      : "主角";

  return (
    <DashboardCardShell
      title="诊断画像"
      icon={<Sparkles className="h-5 w-5" />}
      accent="primary"
      showOrb
      className={cn("flex flex-col", className)}
      bodyClassName="gap-3"
      footer={
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/novels/${novelId}/diagnosis`)}
          className={cn(
            "group flex items-center gap-1 px-0 text-xs text-text-muted transition-colors",
            getMetricAccentHoverTextClass("primary")
          )}
        >
          查看完整诊断报告
          <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Button>
      }
    >
      {!hasFocusContract ? (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/8 px-3 py-3 text-sm text-text-muted">
          当前任务缺少完整焦点合同，请重新分析该任务。
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {diagnosis.narrative_type && (
              <Badge variant="secondary" className="border border-primary/10 bg-primary/10 text-primary">
                {diagnosis.narrative_type}
              </Badge>
            )}
            {diagnosis.narrative_arc_type && (
              <Badge variant="outline" className="border-primary/25 bg-surface/70 text-primary">
                {diagnosis.narrative_arc_type}
              </Badge>
            )}
          </div>

          <div className="grid gap-2.5 md:grid-cols-2">
            {diagnosis.focus_characters && diagnosis.focus_characters.length > 0 && (
              <div className="flex items-center gap-2.5 rounded-xl border border-primary/10 bg-primary/5 px-3 py-2.5 shadow-sm">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <User className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="text-xs uppercase tracking-wide text-text-muted">{focusStructureLabel}</span>
                  <div className="text-sm font-medium text-text">
                    {diagnosis.focus_characters.join(" / ")}
                  </div>
                </div>
              </div>
            )}
            {diagnosis.value_logic_type && (
              <div className="flex items-center gap-2.5 rounded-xl border border-primary/10 bg-primary/5 px-3 py-2.5 shadow-sm">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Target className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="text-xs uppercase tracking-wide text-text-muted">价值逻辑</span>
                  <div className="text-sm font-medium text-text">
                    {diagnosis.value_logic_type}
                  </div>
                </div>
              </div>
            )}
          </div>

          {diagnosis.topic_labels && diagnosis.topic_labels.length > 0 && (
            <div className="rounded-xl border border-border/70 bg-surface/70 p-2.5">
              <div className="mb-1.5 text-xs uppercase tracking-wide text-text-muted">主题标签</div>
              <div className="flex flex-wrap gap-1.5">
                {diagnosis.topic_labels.slice(0, 6).map((label) => (
                  <Badge
                    key={label}
                    variant="secondary"
                    className="border border-primary/10 bg-primary/10 text-[10px] text-primary"
                  >
                    {label}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </DashboardCardShell>
  );
}
