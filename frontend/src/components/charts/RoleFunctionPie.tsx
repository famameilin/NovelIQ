import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { PieChart } from "echarts/charts";
import {
  TooltipComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { ChartPie } from "lucide-react";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { getCSSColorVar } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import type { Character } from "@/api/types";

echarts.use([TooltipComponent, LegendComponent, PieChart, CanvasRenderer]);

// Greimas 六元素映射 - 使用 CSS 变量以支持动态主题
interface GreimasFunction {
  key: string;
  label: string;
  colorVar: string; // CSS 变量名，如 "--chart-1"
  chineseNames: string[]; // 中文别名列表
}

const GREIMAS_FUNCTIONS: GreimasFunction[] = [
  { key: "protagonist", label: "主体", colorVar: "--chart-1", chineseNames: ["主体", "主角"] },
  { key: "antagonist", label: "反对者", colorVar: "--chart-negative", chineseNames: ["反对者", "对手", "反角"] },
  { key: "helper", label: "帮助者", colorVar: "--chart-positive", chineseNames: ["帮助者", "帮手"] },
  { key: "sender", label: "发送者", colorVar: "--chart-2", chineseNames: ["发送者"] },
  { key: "receiver", label: "接收者", colorVar: "--chart-3", chineseNames: ["接收者"] },
  { key: "opponent", label: "反对者", colorVar: "--chart-4", chineseNames: ["反对者", "对手"] },
];

export interface RoleFunctionPieProps {
  /** 角色列表数据 */
  characters: Character[];
  className?: string;
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：统一人物页饼图卡片容器，使可视化区域与其他业务信息卡保持一致。
 */
export function RoleFunctionPie({ characters, className }: RoleFunctionPieProps) {
  const themeSignature = useChartThemeSignature();
  // 统计各功能角色数量
  const functionData = useMemo(() => {
    const counts: Record<string, number> = {};

    GREIMAS_FUNCTIONS.forEach((f) => {
      counts[f.key] = 0;
    });

    characters.forEach((char) => {
      const func = char.dominant_role_function?.trim();
      if (!func) return;

      // 匹配中文或英文功能名
      const matchedFunc = GREIMAS_FUNCTIONS.find(
        (f) => f.key === func.toLowerCase() || f.chineseNames.includes(func)
      );

      if (matchedFunc) {
        counts[matchedFunc.key]++;
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
  }, [characters, themeSignature]);

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
    <DashboardCardShell
      title="角色功能分布"
      icon={<ChartPie className="h-4 w-4" />}
      accent="chart-2"
      className={cn(className)}
      bodyClassName="gap-3"
    >
      <div className="h-[300px] w-full rounded-2xl border border-border/60 bg-surface/70 p-2">
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
            暂无角色功能数据
          </div>
        )}
      </div>
    </DashboardCardShell>
  );
}
