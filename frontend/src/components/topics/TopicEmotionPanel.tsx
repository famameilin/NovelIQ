/**
 * TopicEmotionPanel - 主题情绪关联（赛道 D /topics/emotion）
 *
 * sum(w*t*net_density)/sum(w*t)，分母为加权入模 token 和；空值段落
 * 双向排除，权重和为零的主题显示为空值。
 */
import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import type { TopicEmotionEntry } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, BarChart, CanvasRenderer]);

interface TopicEmotionPanelProps {
  emotion: TopicEmotionEntry[];
  className?: string;
}

export function TopicEmotionPanel({ emotion, className }: TopicEmotionPanelProps) {
  const themeSignature = useChartThemeSignature();

  const option = useMemo(() => {
    const valid = emotion.filter((entry) => entry.emotion != null);
    return {
      tooltip: {
        trigger: "axis",
        formatter: (params: Array<{ dataIndex: number }>) => {
          const entry = valid[params[0]?.dataIndex];
          if (!entry) return "";
          return `主题 ${entry.topic_id}<br/>净情绪 ${entry.emotion?.toFixed(4)}<br/>加权 token ${entry.weighted_token_total ?? "-"}`;
        },
      },
      grid: { left: 56, right: 20, top: 24, bottom: 36 },
      xAxis: {
        type: "category",
        data: valid.map((entry) => `主题 ${entry.topic_id}`),
        axisLabel: { fontSize: 10 },
      },
      yAxis: { type: "value", axisLabel: { fontSize: 10 } },
      series: [
        {
          type: "bar",
          data: valid.map((entry) => entry.emotion),
          barMaxWidth: 32,
        },
      ],
    };
  }, [emotion]);

  return (
    <div className={className}>
      <DashboardCardShell title="主题净情绪关联" accent="chart-5" bodyClassName="min-h-[320px]">
        {emotion.some((entry) => entry.emotion != null) ? (
          <ReactEChartsCore key={themeSignature} option={option} notMerge style={{ height: "100%", width: "100%" }} />
        ) : (
          <p className="flex h-full items-center justify-center text-sm text-text-muted">
            暂无带净情绪的段落曲线数据
          </p>
        )}
      </DashboardCardShell>
    </div>
  );
}
