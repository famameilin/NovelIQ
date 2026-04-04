import { ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SegmentedBar } from "@/components/common/SegmentedBar";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface NarrativeStructureBarProps {
  act1Ratio?: number | null;
  act2Ratio?: number | null;
  act3Ratio?: number | null;
  eventDensity?: Record<string, number> | null;
  novelId: string;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function formatEventDensity(density: Record<string, number> | null | undefined): string | null {
  if (!density || Object.keys(density).length === 0) {
    return null;
  }

  const parts = Object.entries(density).map(([key, value]) => {
    const percentage = Math.round(value * 100);
    return `${key}${percentage}%`;
  });

  return `事件密度: ${parts.join(" ")}`;
}

function hasActData(
  act1: number | null | undefined,
  act2: number | null | undefined,
  act3: number | null | undefined
): boolean {
  return act1 != null || act2 != null || act3 != null;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function NarrativeStructureBar({
  act1Ratio,
  act2Ratio,
  act3Ratio,
  eventDensity,
  novelId,
  className,
}: NarrativeStructureBarProps) {
  const navigate = useNavigate();

  const hasData = hasActData(act1Ratio, act2Ratio, act3Ratio) || eventDensity;

  const segments = hasActData(act1Ratio, act2Ratio, act3Ratio)
    ? [
        {
          label: "引入",
          value: Math.round((act1Ratio ?? 0) * 100),
          colorClass: "bg-chart-1",
        },
        {
          label: "发展",
          value: Math.round((act2Ratio ?? 0) * 100),
          colorClass: "bg-chart-2",
        },
        {
          label: "收束",
          value: Math.round((act3Ratio ?? 0) * 100),
          colorClass: "bg-chart-3",
        },
      ]
    : [];

  const densityText = formatEventDensity(eventDensity);

  return (
    <Card variant="elevated" className={cn("rounded-xl", className)}>
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-text">叙事结构概览</h3>
        </div>

        {hasData ? (
          <>
            {segments.length > 0 && <SegmentedBar segments={segments} />}

            {densityText ? (
              <p className="text-xs text-text-muted">{densityText}</p>
            ) : (
              <p className="text-xs text-text-muted">事件密度: 暂无数据</p>
            )}
          </>
        ) : (
          <p className="text-xs text-text-muted">暂无数据</p>
        )}

        <div className="mt-auto pt-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/novels/${novelId}/timeline`)}
            className="group flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-primary"
          >
            查看叙事时间轴
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
