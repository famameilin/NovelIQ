import { Info } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";

export interface MetricProvenanceProps {
  meaning: string;
  unit: string;
  aggregation: string;
  timing: string;
  className?: string;
}

/**
 * 2026-08-16 提供指标溯源悬浮说明
 * 统一展示指标含义、单位、聚合链路和计算时机，避免卡片脱离数据合同
 */
export function MetricProvenance({
  meaning,
  unit,
  aggregation,
  timing,
  className,
}: MetricProvenanceProps) {
  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label="查看指标口径"
            className={cn(
              "inline-flex h-5 w-5 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
              className,
            )}
          >
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs space-y-1.5 leading-5">
          <p><span className="font-medium">含义：</span>{meaning}</p>
          <p><span className="font-medium">单位：</span>{unit}</p>
          <p><span className="font-medium">由何聚合：</span>{aggregation}</p>
          <p><span className="font-medium">何时计算：</span>{timing}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
