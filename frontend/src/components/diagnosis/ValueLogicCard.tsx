import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { Scale } from "lucide-react";

export interface ValueLogicCardProps {
  /** 价值逻辑类型 */
  valueLogicType?: string | null;
  /** 价值逻辑原因说明 */
  valueLogicReason?: string | null;
  className?: string;
}

/**
 * 价值逻辑卡片 - 展示小说的价值逻辑类型和原因
 */
export function ValueLogicCard({
  valueLogicType,
  valueLogicReason,
  className,
}: ValueLogicCardProps) {
  return (
    <Card variant="elevated" className={cn("rounded-xl overflow-hidden", className)}>
      <CardContent className="flex flex-col gap-3 p-5">
        <div className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-text-muted" />
          <h4 className="text-sm font-semibold text-text">价值逻辑</h4>
        </div>

        {valueLogicType ? (
          <div className="flex flex-col gap-2">
            <div className="inline-flex items-center rounded-full bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary w-fit">
              {valueLogicType}
            </div>
            {valueLogicReason && (
              <p className="text-xs text-text-muted leading-relaxed">
                {valueLogicReason}
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-text-muted">暂无价值逻辑数据</p>
        )}
      </CardContent>
    </Card>
  );
}