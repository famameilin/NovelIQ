import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { RadarChart } from "echarts/charts";
import {
  TitleComponent,
  TooltipComponent,
  RadarComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getEChartsColors, hslToHsla } from "@/lib/theme";
import { cn } from "@/lib/cn";
import type { RadarDimension } from "@/lib/normalize";

echarts.use([
  TitleComponent,
  TooltipComponent,
  RadarComponent,
  RadarChart,
  CanvasRenderer,
]);

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface FiveDimensionRadarProps {
  dimensions: RadarDimension[];
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function FiveDimensionRadar({
  dimensions,
  className,
}: FiveDimensionRadarProps) {
  const colors = useMemo(() => getEChartsColors(), []);

  const option = useMemo(
    () => ({
      color: colors,
      tooltip: {
        trigger: "item" as const,
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 12 },
      },
      radar: {
        indicator: dimensions.map((d) => ({
          name: d.name,
          max: 100,
        })),
        shape: "polygon" as const,
        splitNumber: 5,
        center: ["50%", "54%"],
        radius: "70%",
        axisName: {
          color: "hsl(var(--text-secondary))",
          fontSize: 12,
        },
        splitArea: {
          areaStyle: {
            color: [
              "hsl(var(--border-subtle) / 0.3)",
              "hsl(var(--border-subtle) / 0.15)",
            ],
          },
        },
        axisLine: {
          lineStyle: { color: "hsl(var(--border))" },
        },
        splitLine: {
          lineStyle: { color: "hsl(var(--border))" },
        },
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: dimensions.map((d) => d.value),
              name: "综合评分",
              areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: colors[0] },
                  { offset: 1, color: hslToHsla(colors[0], 0.1) },
                ]),
              },
              lineStyle: { width: 2 },
              itemStyle: {
                borderColor: colors[0],
                borderWidth: 2,
              },
              symbol: "circle",
              symbolSize: 6,
            },
          ],
        },
      ],
      animationDuration: 800,
      animationEasing: "cubicOut" as const,
    }),
    [dimensions, colors],
  );

  return (
    <div
      className={cn("w-full", className)}
      style={{ minHeight: 260 }}
    >
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: "100%", width: "100%" }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}
