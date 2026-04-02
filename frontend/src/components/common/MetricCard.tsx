import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatNumber, formatPercent } from "@/lib/utils";

export type MetricFormat = "number" | "percent" | "score" | "raw";

export interface MetricCardProps {
  /** Display label for the metric */
  label: string;
  /** Raw numeric value */
  value: number;
  /** How to format the value for display */
  format?: MetricFormat;
  /** Maximum value for score bar (only used when format="score") */
  maxScore?: number;
  /** Number of decimal places */
  decimals?: number;
  /** Optional icon rendered before the label */
  icon?: ReactNode;
  /** Optional tooltip describing the metric */
  description?: string;
  /** Additional className */
  className?: string;
}

function formatValue(
  value: number,
  format: MetricFormat,
  decimals: number,
  maxScore: number
): string {
  switch (format) {
    case "percent":
      return formatPercent(value, decimals);
    case "score":
      return `${formatNumber(value, decimals)}/${maxScore}`;
    case "number":
      return formatNumber(value, decimals);
    case "raw":
    default:
      return String(value);
  }
}

export function MetricCard({
  label,
  value,
  format = "number",
  maxScore = 5,
  decimals = 1,
  icon,
  description,
  className,
}: MetricCardProps) {
  const displayValue = formatValue(value, format, decimals, maxScore);

  // Bar fill ratio for score and percent modes
  const fillRatio =
    format === "score"
      ? Math.min(value / maxScore, 1)
      : format === "percent"
        ? Math.min(value, 1)
        : 0;
  const showBar = format === "score" || format === "percent";

  const content = (
    <Card
      className={cn(
        "group transition-shadow hover:shadow-md",
        className
      )}
    >
      <CardContent className="flex flex-col gap-2 p-4">
        <div className="flex items-center gap-2 text-text-muted">
          {icon && <span className="shrink-0">{icon}</span>}
          <span className="text-xs font-medium uppercase tracking-wide">
            {label}
          </span>
        </div>

        <div className="text-2xl font-bold tabular-nums text-text">
          {displayValue}
        </div>

        {showBar && (
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-border">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500"
              style={{ width: `${fillRatio * 100}%` }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );

  if (!description) return content;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent side="top" className="max-w-xs">
        <p>{description}</p>
      </TooltipContent>
    </Tooltip>
  );
}
