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
  /** 主角名称，用于高亮 */
  protagonist?: string | null;
  /** 最多显示数量 */
  limit?: number;
  className?: string;
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：统一人物页图表卡片的容器视觉，让排名图与其他业务卡片共享同一设计语言。
 */
export function CharacterRankingBar({
  characters,
  protagonist,
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
      if (c.name === protagonist) {
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
          color: (value: string) => (value === protagonist ? primaryColor : "hsl(var(--text))"),
          fontSize: 12,
          fontWeight: (value: string) => (value === protagonist ? 600 : 400),
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
  }, [sortedCharacters, protagonist, primaryColor]);

  const hasData = sortedCharacters.length > 0;

  return (
    <DashboardCardShell
      title="角色出场排名"
      icon={<BarChart3 className="h-4 w-4" />}
      accent="primary"
      showOrb
      className={cn(className)}
      bodyClassName="gap-3"
    >
      <div className="h-[400px] w-full rounded-2xl border border-border/60 bg-surface/70 p-2">
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
