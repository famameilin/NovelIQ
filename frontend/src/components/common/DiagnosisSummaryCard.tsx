import { User, Target, Sparkles, ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function DiagnosisSummaryCard({
  diagnosis,
  novelId,
  className,
}: DiagnosisSummaryCardProps) {
  const navigate = useNavigate();

  return (
    <Card variant="elevated" className={cn("flex flex-col", className)}>
      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-text">诊断画像</h3>
        </div>

        <div className="flex flex-wrap gap-2">
          {diagnosis.narrative_type && (
            <Badge variant="secondary">{diagnosis.narrative_type}</Badge>
          )}
          {diagnosis.narrative_arc_type && (
            <Badge variant="outline">{diagnosis.narrative_arc_type}</Badge>
          )}
        </div>

        <div className="flex flex-col gap-3">
          {diagnosis.protagonist && (
            <div className="flex items-center gap-3">
              <User className="h-4 w-4 shrink-0 text-text-muted" />
              <div className="min-w-0 flex-1">
                <span className="text-sm text-text-muted">主角: </span>
                <span className="text-sm font-medium text-text">
                  {diagnosis.protagonist}
                </span>
              </div>
            </div>
          )}
          {diagnosis.value_logic_type && (
            <div className="flex items-center gap-3">
              <Target className="h-4 w-4 shrink-0 text-text-muted" />
              <div className="min-w-0 flex-1">
                <span className="text-sm text-text-muted">价值逻辑: </span>
                <span className="text-sm font-medium text-text">
                  {diagnosis.value_logic_type}
                </span>
              </div>
            </div>
          )}
        </div>

        {diagnosis.topic_labels && diagnosis.topic_labels.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {diagnosis.topic_labels.slice(0, 6).map((label) => (
              <Badge key={label} variant="secondary" className="text-[10px]">
                {label}
              </Badge>
            ))}
          </div>
        )}

        <div className="mt-auto pt-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/novels/${novelId}/diagnosis`)}
            className="group flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-primary"
          >
            查看完整诊断报告
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
