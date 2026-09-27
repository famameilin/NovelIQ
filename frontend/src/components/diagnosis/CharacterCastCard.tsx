import { useState } from "react";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { PagedControls } from "@/components/common/PagedControls";
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
  const [pages, setPages] = useState({ focus: 1, core: 1, major: 1 });
  const hasData =
    (focusCharacters && focusCharacters.length > 0) || (coreCast && coreCast.length > 0) || (majorCast && majorCast.length > 0);
  const groups = [
    { key: "focus", title: getFocusStructureLabel(focusStructure), names: focusCharacters ?? [] },
    { key: "core", title: "核心角色", names: coreCast ?? [] },
    { key: "major", title: "主要角色", names: majorCast ?? [] },
  ] as const;

  return (
    <DashboardCardShell
      title="角色阵容"
      icon={<Users className="h-4 w-4" />}
      accent="chart-1"
      showOrb
      className={cn(className)}
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1"
    >
      {hasData ? (
        <div className="grid min-h-0 flex-1 grid-rows-3 gap-2">
          {groups.map(({ key, title, names }) => {
            const pageCount = Math.ceil(names.length / 4);
            const currentPage = Math.min(pages[key], Math.max(pageCount, 1));
            return (
              <section key={key} className="flex min-h-0 flex-col justify-center rounded-xl border border-border/60 bg-surface/70 px-3 py-2">
                <div className="flex items-center justify-between text-xs">
                  <h3 className="font-medium text-text">{title}</h3>
                  <span className="tabular-nums text-text-muted">{names.length} 人</span>
                </div>
                {names.length > 0 ? (
                  <div className="mt-2 grid grid-cols-2 gap-1.5">
                    {names.slice((currentPage - 1) * 4, currentPage * 4).map((name, index) => (
                      <span key={`${name}-${index}`} className="truncate rounded-md bg-primary/10 px-2 py-1 text-xs text-primary" title={name}>{name}</span>
                    ))}
                  </div>
                ) : <p className="mt-2 text-xs text-text-muted">暂无该类角色</p>}
                <PagedControls page={currentPage} pageCount={pageCount}
                  onPageChange={(next) => setPages((current) => ({ ...current, [key]: next }))} label={title} />
              </section>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-text-muted">暂无角色数据</p>
      )}
    </DashboardCardShell>
  );
}
