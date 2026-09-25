/**
 * PosSimilarityHeatmap - POS 质心余弦相似度热力图
 *
 * 数据为服务端计算的对称矩阵（对角线 1），行序与 pos_centroids 一致；
 * 语义组成对照需结合词性覆盖解释，同维度内比较。
 */
import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";

echarts.use([GridComponent, TooltipComponent, VisualMapComponent, HeatmapChart, CanvasRenderer]);

interface PosSimilarityHeatmapProps {
  groups: string[];
  matrix: number[][];
  className?: string;
}

export function PosSimilarityHeatmap({ groups, matrix, className }: PosSimilarityHeatmapProps) {
  const themeSignature = useChartThemeSignature();

  const option = useMemo(() => {
    const data: Array<[number, number, number]> = [];
    matrix.forEach((row, rowIndex) => {
      row.forEach((value, colIndex) => {
        data.push([colIndex, rowIndex, value]);
      });
    });
    return {
      tooltip: {
        position: "top",
        formatter: (params: { value: [number, number, number] }) =>
          `${groups[params.value[0]]} × ${groups[params.value[1]]}：${params.value[2].toFixed(4)}`,
      },
      grid: { left: 80, right: 24, top: 16, bottom: 72 },
      xAxis: { type: "category", data: groups, axisLabel: { fontSize: 10, rotate: 30 } },
      yAxis: { type: "category", data: groups, axisLabel: { fontSize: 10 } },
      visualMap: {
        min: -1,
        max: 1,
        calculable: true,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        inRange: { color: ["#4a6fa5", "#f5f0e8", "#c25b4e"] },
        textStyle: { fontSize: 10 },
      },
      series: [
        {
          type: "heatmap",
          data,
          label: { show: matrix.length <= 8, fontSize: 9, formatter: (params: { value: [number, number, number] }) => params.value[2].toFixed(2) },
        },
      ],
    };
  }, [groups, matrix]);

  return (
    <div className={className}>
      <ReactEChartsCore key={themeSignature} option={option} notMerge style={{ height: "100%", width: "100%" }} />
    </div>
  );
}
