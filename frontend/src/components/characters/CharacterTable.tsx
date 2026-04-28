import { useMemo, useState } from "react";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ChevronUp, ChevronDown, User } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Character } from "@/api/types";

export interface CharacterTableProps {
  /** 角色列表数据 */
  characters: Character[];
  className?: string;
}

type SortKey = "name" | "appearance_count" | "dominant_role_function" | "narrative_focus_score" | "avg_emotion_score";
type SortDirection = "asc" | "desc";

function SortIcon({
  column,
  sortKey,
  sortDirection,
}: {
  column: SortKey;
  sortKey: SortKey;
  sortDirection: SortDirection;
}) {
  if (sortKey !== column) return null;
  return sortDirection === "asc" ? (
    <ChevronUp className="h-3 w-3" />
  ) : (
    <ChevronDown className="h-3 w-3" />
  );
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：统一人物页表格容器样式，减少页面上普通 Card 与新卡片壳并存的割裂感
 *
 * 2026-04-27，任务：protagonist-focus-contract
 * 修改原因：表格列和高亮逻辑统一切到焦点合同，展示 `narrative_focus_score`，
 * 并直接消费角色结果里的 `is_focus_character`，不再依赖额外的名称列表高亮
 */
export function CharacterTable({
  characters,
  className,
}: CharacterTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("appearance_count");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const sortedCharacters = useMemo(() => {
    return [...characters].sort((a, b) => {
      let aVal: number | string | undefined;
      let bVal: number | string | undefined;

      switch (sortKey) {
        case "name":
          aVal = a.name;
          bVal = b.name;
          break;
        case "appearance_count":
          aVal = a.appearance_count;
          bVal = b.appearance_count;
          break;
        case "dominant_role_function":
          aVal = a.dominant_role_function || "";
          bVal = b.dominant_role_function || "";
          break;
        case "narrative_focus_score":
          aVal = a.narrative_focus_score ?? 0;
          bVal = b.narrative_focus_score ?? 0;
          break;
        case "avg_emotion_score":
          aVal = a.avg_emotion_score ?? 0;
          bVal = b.avg_emotion_score ?? 0;
          break;
      }

      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDirection === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }

      const aNum = (aVal as number) ?? 0;
      const bNum = (bVal as number) ?? 0;
      return sortDirection === "asc" ? aNum - bNum : bNum - aNum;
    });
  }, [characters, sortKey, sortDirection]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDirection("desc");
    }
  };

  return (
    <DashboardCardShell
      title="角色完整列表"
      icon={<User className="h-4 w-4" />}
      accent="chart-4"
      className={cn(className)}
      bodyClassName="gap-3"
    >
      <div className="max-h-[400px] overflow-auto rounded-xl border border-border/70 bg-surface/70">
        <Table>
          <TableHeader>
            <TableRow className="bg-surface-hover">
              <TableHead className="w-[150px] cursor-pointer" onClick={() => handleSort("name")}>
                <div className="flex items-center gap-1">
                  名称
                  <SortIcon column="name" sortKey={sortKey} sortDirection={sortDirection} />
                </div>
              </TableHead>
              <TableHead className="cursor-pointer" onClick={() => handleSort("appearance_count")}>
                <div className="flex items-center gap-1">
                  出场次数
                  <SortIcon column="appearance_count" sortKey={sortKey} sortDirection={sortDirection} />
                </div>
              </TableHead>
              <TableHead className="cursor-pointer" onClick={() => handleSort("dominant_role_function")}>
                <div className="flex items-center gap-1">
                  主导功能
                  <SortIcon column="dominant_role_function" sortKey={sortKey} sortDirection={sortDirection} />
                </div>
              </TableHead>
              <TableHead className="cursor-pointer" onClick={() => handleSort("narrative_focus_score")}>
                <div className="flex items-center gap-1">
                  叙事中心度
                  <SortIcon column="narrative_focus_score" sortKey={sortKey} sortDirection={sortDirection} />
                </div>
              </TableHead>
              <TableHead className="cursor-pointer" onClick={() => handleSort("avg_emotion_score")}>
                <div className="flex items-center gap-1">
                  情绪均值
                  <SortIcon column="avg_emotion_score" sortKey={sortKey} sortDirection={sortDirection} />
                </div>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedCharacters.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-32 text-center text-sm text-text-muted">
                  暂无角色数据
                </TableCell>
              </TableRow>
            ) : (
              sortedCharacters.map((char) => (
                <TableRow
                  key={char.name}
                  className={cn(
                    "cursor-pointer transition-colors hover:bg-surface-hover",
                    char.is_focus_character && "bg-primary/5"
                  )}
                >
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2">
                      {char.is_focus_character && (
                        <User className="h-3 w-3 text-primary" />
                      )}
                      <span className={char.is_focus_character ? "text-primary font-semibold" : ""}>
                        {char.name}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>{char.appearance_count}</TableCell>
                  <TableCell>
                    {char.dominant_role_function ? (
                      <Badge variant="secondary" className="text-[10px]">
                        {char.dominant_role_function}
                      </Badge>
                    ) : (
                      <span className="text-text-muted">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {char.narrative_focus_score != null ? (
                      <span className="tabular-nums">{char.narrative_focus_score.toFixed(1)}</span>
                    ) : (
                      <span className="text-text-muted">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {char.avg_emotion_score != null ? (
                      <span
                        className={cn(
                          "tabular-nums",
                          char.avg_emotion_score > 0.1
                            ? "text-chart-positive"
                            : char.avg_emotion_score < -0.1
                            ? "text-chart-negative"
                            : "text-text-muted"
                        )}
                      >
                        {char.avg_emotion_score > 0 ? "+" : ""}
                        {char.avg_emotion_score.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-text-muted">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </DashboardCardShell>
  );
}
