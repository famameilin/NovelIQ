import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart3 } from "lucide-react";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { getCSSColorVar, hslToHsla } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import type { Character } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, BarChart, CanvasRenderer]);

export interface CharacterRankingBarProps {
  /** 角色列表数据 */
  characters: Character[];
  /** 最多显示数量 */
  limit?: number;
  className?: string;
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：统一人物页图表卡片的容器视觉，让排名图与其他业务卡片共享同一设计语言
 *
 * 2026-04-27，任务：protagonist-focus-contract
 * 修改原因：人物页现在支持多焦点高亮；排名图直接消费 `is_focus_character`
 * 做强调显示，不再依赖额外的焦点名称列表，也不再假定只有一个 protagonist
 *
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：图表卡片需要在 tab 工作区内跟随父容器高度伸缩，避免固定高度撑破单屏布局
 */
export function CharacterRankingBar({
  characters,
  limit = 15,
  className,
}: CharacterRankingBarProps) {
  const themeSignature = useChartThemeSignature();
  const primaryColor = getCSSColorVar("--primary");

  // 按出场次数排序，取前 N 个
  const sortedCharacters = useMemo(() => {
    return [...characters]
      .sort((a, b) => b.appearance_count - a.appearance_count)
      .slice(0, limit);
  }, [characters, limit]);

  const option = useMemo(() => {
    if (sortedCharacters.length === 0) return {};

    // 反转顺序，让排名第一的在最上面
    const names = [...sortedCharacters].reverse().map((c) => c.name);
    const counts = [...sortedCharacters].reverse().map((c) => c.appearance_count);

    // 为每个角色计算颜色（主角高亮）
    const colors = [...sortedCharacters].reverse().map((c) => {
      if (c.is_focus_character) {
        return primaryColor;
      }
      return hslToHsla(primaryColor, 0.5);
    });

    return {
      grid: { top: 10, right: 40, bottom: 10, left: 80, containLabel: false },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "shadow" as const },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 12 },
        formatter: (params: Array<{ name: string; value: number; marker: string }>) => {
          const p = params[0];
          const char = sortedCharacters.find((c) => c.name === p.name);
          let text = `${p.name}<br/>${p.marker} 出场次数: ${p.value}`;
          if (char?.dominant_role_function) {
            text += `<br/>${p.marker} 功能: ${char.dominant_role_function}`;
          }
          return text;
        },
      },
      xAxis: {
        type: "value" as const,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "hsl(var(--text-muted))", fontSize: 11 },
        splitLine: { lineStyle: { color: "hsl(var(--border))", type: "dashed" } },
      },
      yAxis: {
        type: "category" as const,
        data: names,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: (value: string) => {
            const character = sortedCharacters.find((item) => item.name === value);
            return character?.is_focus_character ? primaryColor : "hsl(var(--text))";
          },
          fontSize: 12,
          fontWeight: (value: string) => {
            const character = sortedCharacters.find((item) => item.name === value);
            return character?.is_focus_character ? 600 : 400;
          },
        },
      },
      series: [
        {
          name: "出场次数",
          type: "bar",
          data: counts,
          barWidth: "60%",
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color: (params: { dataIndex: number }) => colors[params.dataIndex],
          },
          label: {
            show: true,
            position: "right",
            formatter: "{c}",
            color: "hsl(var(--text-muted))",
            fontSize: 11,
          },
          animationDuration: 800,
          animationEasing: "cubicOut",
        },
      ],
    };
  }, [sortedCharacters, primaryColor]);

  const hasData = sortedCharacters.length > 0;

  return (
    <DashboardCardShell
      title="角色出场排名"
      icon={<BarChart3 className="h-4 w-4" />}
      accent="primary"
      showOrb
      className={cn(className)}
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1 gap-3"
    >
      <div className="min-h-[260px] flex-1 w-full rounded-2xl border border-border/60 bg-surface/70 p-2">
        {hasData ? (
          <ReactEChartsCore
            key={themeSignature}
            echarts={echarts}
            option={option}
            style={{ height: "100%", width: "100%" }}
            notMerge
            lazyUpdate
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-text-muted">
            暂无角色数据
          </div>
        )}
      </div>
    </DashboardCardShell>
  );
}
