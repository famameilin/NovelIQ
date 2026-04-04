import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { Card, CardContent } from "@/components/ui/card";
import { getCSSColorVar, hslToHsla } from "@/lib/theme";
import { cn } from "@/lib/cn";
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
 * 角色出场排名横向柱状图
 */
export function CharacterRankingBar({
  characters,
  protagonist,
  limit = 15,
  className,
}: CharacterRankingBarProps) {
  const primaryColor = getCSSColorVar("--primary");

  // 按出场次数排序，取前 N 个
  const sortedCharacters = useMemo(() => {
    return [...characters]
      .sort((a, b) => b.count - a.count)
      .slice(0, limit);
  }, [characters, limit]);

  const option = useMemo(() => {
    if (sortedCharacters.length === 0) return {};

    // 反转顺序，让排名第一的在最上面
    const names = [...sortedCharacters].reverse().map((c) => c.name);
    const counts = [...sortedCharacters].reverse().map((c) => c.count);

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
          if (char?.dominant_function) {
            text += `<br/>${p.marker} 功能: ${char.dominant_function}`;
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
    <Card variant="elevated" className={cn("rounded-xl overflow-hidden", className)}>
      <CardContent className="flex flex-col gap-3 p-5">
        <h4 className="text-sm font-semibold text-text">角色出场排名</h4>

        <div className="h-[400px] w-full">
          {hasData ? (
            <ReactEChartsCore
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
      </CardContent>
    </Card>
  );
}