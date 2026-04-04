import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { PieChart } from "echarts/charts";
import {
  TooltipComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { Card, CardContent } from "@/components/ui/card";
import { getCSSColorVar } from "@/lib/theme";
import { cn } from "@/lib/cn";
import type { Character } from "@/api/types";

echarts.use([TooltipComponent, LegendComponent, PieChart, CanvasRenderer]);

// Greimas 六元素映射 - 使用 CSS 变量以支持动态主题
interface GreimasFunction {
  key: string;
  label: string;
  colorVar: string; // CSS 变量名，如 "--chart-1"
}

const GREIMAS_FUNCTIONS: GreimasFunction[] = [
  { key: "protagonist", label: "主角", colorVar: "--chart-1" },
  { key: "antagonist", label: "反角", colorVar: "--chart-negative" },
  { key: "helper", label: "帮手", colorVar: "--chart-positive" },
  { key: "sender", label: "发送者", colorVar: "--chart-2" },
  { key: "receiver", label: "接受者", colorVar: "--chart-3" },
  { key: "opponent", label: "对手", colorVar: "--chart-4" },
];

export interface RoleFunctionPieProps {
  /** 角色列表数据 */
  characters: Character[];
  className?: string;
}

/**
 * 角色功能分布饼图 - Greimas 六元素模型
 */
export function RoleFunctionPie({ characters, className }: RoleFunctionPieProps) {
  // 统计各功能角色数量
  const functionData = useMemo(() => {
    const counts: Record<string, number> = {};

    GREIMAS_FUNCTIONS.forEach((f) => {
      counts[f.key] = 0;
    });

    characters.forEach((char) => {
      const func = char.dominant_function?.toLowerCase();
      if (func && counts[func] !== undefined) {
        counts[func]++;
      } else if (char.protagonist_score && char.protagonist_score >= 4) {
        // 高主角分的默认为 protagonist
        counts["protagonist"]++;
      }
    });

    // 过滤掉数量为 0 的，并解析 CSS 变量为运行时颜色值
    return GREIMAS_FUNCTIONS
      .filter((f) => counts[f.key] > 0)
      .map((f) => ({
        name: f.label,
        value: counts[f.key],
        itemStyle: { color: getCSSColorVar(f.colorVar) },
      }));
  }, [characters]);

  const option = useMemo(() => {
    if (functionData.length === 0) return {};

    return {
      tooltip: {
        trigger: "item" as const,
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 12 },
        formatter: "{b}: {c} 人 ({d}%)",
      },
      legend: {
        orient: "vertical" as const,
        right: 10,
        top: "center",
        textStyle: { color: "hsl(var(--text))", fontSize: 12 },
      },
      series: [
        {
          name: "角色功能",
          type: "pie",
          radius: ["40%", "70%"],
          center: ["35%", "50%"],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 6,
            borderColor: "hsl(var(--surface))",
            borderWidth: 2,
          },
          label: {
            show: false,
          },
          emphasis: {
            label: {
              show: true,
              fontSize: 14,
              fontWeight: "bold",
            },
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: "rgba(0, 0, 0, 0.3)",
            },
          },
          labelLine: {
            show: false,
          },
          data: functionData,
          animationType: "scale",
          animationEasing: "elasticOut",
          animationDuration: 1000,
        },
      ],
    };
  }, [functionData]);

  const hasData = functionData.length > 0;

  return (
    <Card variant="elevated" className={cn("rounded-xl overflow-hidden", className)}>
      <CardContent className="flex flex-col gap-3 p-5">
        <h4 className="text-sm font-semibold text-text">角色功能分布</h4>

        <div className="h-[300px] w-full">
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
              暂无角色功能数据
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}