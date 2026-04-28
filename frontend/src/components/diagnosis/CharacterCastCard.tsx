import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { cn } from "@/lib/cn";
import { Users } from "lucide-react";

export interface CharacterCastCardProps {
  /** 焦点结构 */
  focusStructure?: "single" | "dual" | "ensemble";
  /** 焦点人物名称列表 */
  focusCharacters?: string[] | null;
  /** 核心角色列表 */
  coreCast?: string[] | null;
  /** 主要角色列表 */
  majorCast?: string[] | null;
  className?: string;
}

function getFocusStructureLabel(focusStructure?: "single" | "dual" | "ensemble") {
  switch (focusStructure) {
    case "dual":
      return "双主角";
    case "ensemble":
      return "群像焦点";
    default:
      return "主角";
  }
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：统一诊断页角色阵容卡的容器和标签层次，让它与仪表盘卡片保持一致
 *
 * 2026-04-27，任务：protagonist-focus-contract
 * 修改原因：角色阵容卡改为展示焦点结构与焦点人物列表，不再假定 diagnosis 只会给出单个主角
 */
export function CharacterCastCard({
  focusStructure,
  focusCharacters,
  coreCast,
  majorCast,
  className,
}: CharacterCastCardProps) {
  const hasData =
    (focusCharacters && focusCharacters.length > 0) || (coreCast && coreCast.length > 0) || (majorCast && majorCast.length > 0);

  return (
    <DashboardCardShell
      title="角色阵容"
      icon={<Users className="h-4 w-4" />}
      accent="chart-1"
      showOrb
      className={cn(className)}
      bodyClassName="gap-3"
    >
      {hasData ? (
        <div className="flex flex-col gap-3">
          {focusCharacters && focusCharacters.length > 0 && (
            <div className="rounded-2xl border border-border/60 bg-surface/70 px-4 py-3">
              <span className="text-xs text-text-muted">{getFocusStructureLabel(focusStructure)}</span>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {focusCharacters.map((characterName) => (
                  <span
                    key={characterName}
                    className="inline-flex w-fit items-center rounded-full bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
                  >
                    {characterName}
                  </span>
                ))}
              </div>
            </div>
          )}

          {coreCast && coreCast.length > 0 && (
            <div className="rounded-2xl border border-border/60 bg-surface/70 px-4 py-3">
              <span className="text-xs text-text-muted">核心角色</span>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {coreCast.map((char, index) => (
                  <span
                    key={index}
                    className="rounded-md bg-chart-1/12 px-2 py-1 text-xs text-chart-1"
                  >
                    {char}
                  </span>
                ))}
              </div>
            </div>
          )}

          {majorCast && majorCast.length > 0 && (
            <div className="rounded-2xl border border-border/60 bg-surface/70 px-4 py-3">
              <span className="text-xs text-text-muted">主要角色</span>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {majorCast.map((char, index) => (
                  <span
                    key={index}
                    className="rounded-md bg-chart-2/12 px-2 py-1 text-xs text-chart-2"
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
    </DashboardCardShell>
  );
}
