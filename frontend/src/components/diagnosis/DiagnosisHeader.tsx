import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export interface DiagnosisHeaderProps {
  /** 叙事类型 */
  narrativeType?: string | null;
  /** 弧线类型 */
  arcType?: string | null;
  className?: string;
}

/**
 * 诊断头部 - 展示叙事类型和弧线类型标签
 */
export function DiagnosisHeader({
  narrativeType,
  arcType,
  className,
}: DiagnosisHeaderProps) {
  const hasData = narrativeType || arcType;

  if (!hasData) {
    return null;
  }

  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {narrativeType && (
        <Badge variant="secondary" className="text-xs">
          {narrativeType}
        </Badge>
      )}
      {arcType && (
        <Badge variant="outline" className="text-xs">
          {arcType}
        </Badge>
      )}
    </div>
  );
}