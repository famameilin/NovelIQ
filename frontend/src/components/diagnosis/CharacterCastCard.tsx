import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { Users } from "lucide-react";

export interface CharacterCastCardProps {
  /** 主角名称 */
  protagonist?: string | null;
  /** 核心角色列表 */
  coreCast?: string[] | null;
  /** 主要角色列表 */
  majorCast?: string[] | null;
  className?: string;
}

/**
 * 角色阵容卡片 - 展示主角、核心角色、主要角色
 */
export function CharacterCastCard({
  protagonist,
  coreCast,
  majorCast,
  className,
}: CharacterCastCardProps) {
  const hasData = protagonist || (coreCast && coreCast.length > 0) || (majorCast && majorCast.length > 0);

  return (
    <Card variant="elevated" className={cn("rounded-xl overflow-hidden", className)}>
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-text-muted" />
          <h4 className="text-sm font-semibold text-text">角色阵容</h4>
        </div>

        {hasData ? (
          <div className="flex flex-col gap-4">
            {protagonist && (
              <div className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">主角</span>
                <div className="inline-flex items-center rounded-full bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary w-fit">
                  {protagonist}
                </div>
              </div>
            )}

            {coreCast && coreCast.length > 0 && (
              <div className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">核心角色</span>
                <div className="flex flex-wrap gap-1.5">
                  {coreCast.map((char, index) => (
                    <span
                      key={index}
                      className="rounded-md bg-chart-1/10 px-2 py-1 text-xs text-chart-1"
                    >
                      {char}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {majorCast && majorCast.length > 0 && (
              <div className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">主要角色</span>
                <div className="flex flex-wrap gap-1.5">
                  {majorCast.map((char, index) => (
                    <span
                      key={index}
                      className="rounded-md bg-chart-2/10 px-2 py-1 text-xs text-chart-2"
                    >
                      {char}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-text-muted">暂无角色数据</p>
        )}
      </CardContent>
    </Card>
  );
}