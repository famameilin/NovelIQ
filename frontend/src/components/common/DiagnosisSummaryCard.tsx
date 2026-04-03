import {
  BookOpen,
  User,
  TrendingUp,
  Target,
  Sparkles,
  ArrowRight,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/cn";
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
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value?: string | number | null;
}) {
  if (!value && value !== 0) return null;
  return (
    <div className="flex items-start gap-3">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-text-muted" />
      <div className="min-w-0 flex-1">
        <p className="text-xs text-text-muted">{label}</p>
        {typeof value === "string" ? (
          <span className="text-sm font-medium text-text">{value}</span>
        ) : (
          <span className="text-sm font-medium text-text">
            {(value as number).toFixed(1)}
          </span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function DiagnosisSummaryCard({
  diagnosis,
  novelId,
  className,
}: DiagnosisSummaryCardProps) {
  const navigate = useNavigate();

  const foreshadowPct =
    diagnosis.foreshadow_rate != null
      ? Math.round(diagnosis.foreshadow_rate * 100)
      : null;

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        {/* Title */}
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-text">诊断摘要</h3>
        </div>

        {/* Info rows */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-3">
          <InfoRow
            icon={BookOpen}
            label="叙事类型"
            value={diagnosis.narrative_type}
          />
          <InfoRow icon={User} label="主角" value={diagnosis.protagonist} />
          <InfoRow
            icon={TrendingUp}
            label="叙事弧线"
            value={diagnosis.arc_type}
          />
          <InfoRow
            icon={Target}
            label="价值逻辑"
            value={diagnosis.value_logic_type}
          />
        </div>

        {/* Foreshadow rate progress bar */}
        {foreshadowPct != null && (
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs text-text-muted">伏笔兑现率</span>
              <span className="text-xs font-medium tabular-nums text-text">
                {foreshadowPct}%
              </span>
            </div>
            <Progress value={foreshadowPct} />
          </div>
        )}

        {/* Topic labels */}
        {diagnosis.topic_labels && diagnosis.topic_labels.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {diagnosis.topic_labels.slice(0, 6).map((label) => (
              <Badge key={label} variant="secondary" className="text-[10px]">
                {label}
              </Badge>
            ))}
          </div>
        )}

        {/* Footer: link to full diagnosis */}
        <div className="mt-auto pt-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/novels/${novelId}/diagnosis`)}
            className="group flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-primary"
          >
            查看完整诊断
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
