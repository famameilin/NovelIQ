/**
 * TopicDistributionChart - 主题完整分布柱状图（赛道 D）
 *
 * book 视图：全书 K 维完整分布（含零权重主题，不补零截断）；
 * chapter 视图：按 chapters.sequence 排列的章节级 K 维堆积柱。
 */
import { useMemo, useState } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import { getCSSColorVar } from "@/lib/theme";
import type { ChapterTopicDistribution, TopicDistributionEntry } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, LegendComponent, BarChart, CanvasRenderer]);

interface TopicDistributionChartProps {
  distribution: TopicDistributionEntry[] | null;
  chapters: ChapterTopicDistribution[];
  className?: string;
}

type DistributionView = "book" | "chapter";

export function TopicDistributionChart({ distribution, chapters, className }: TopicDistributionChartProps) {
  const themeSignature = useChartThemeSignature();
  const [view, setView] = useState<DistributionView>("book");

  const primaryColor = getCSSColorVar("--chart-3");

  const option = useMemo(() => {
    if (view === "book") {
      const entries = distribution ?? [];
      return {
        tooltip: { trigger: "axis" },
        grid: { left: 48, right: 16, top: 24, bottom: 32 },
        xAxis: {
          type: "category",
          data: entries.map((entry) => `主题 ${entry.topic_id}`),
          axisLabel: { fontSize: 10 },
        },
        yAxis: { type: "value", axisLabel: { fontSize: 10 } },
        series: [
          {
            name: "全书权重",
            type: "bar",
            data: entries.map((entry) => entry.weight),
            itemStyle: { color: primaryColor, borderRadius: [3, 3, 0, 0] },
          },
        ],
      };
    }

    const chapterEntries = chapters.filter((chapter) => chapter.distribution != null);
    const topicCount = chapterEntries[0]?.distribution?.length ?? 0;
    return {
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 10 } },
      grid: { left: 48, right: 16, top: 24, bottom: 56 },
      xAxis: {
        type: "category",
        data: chapterEntries.map((chapter) => `第${chapter.chapter_sequence}章`),
        axisLabel: { fontSize: 10 },
      },
      yAxis: { type: "value", axisLabel: { fontSize: 10 } },
      series: Array.from({ length: topicCount }, (_, topicId) => ({
        name: `主题 ${topicId}`,
        type: "bar",
        stack: "distribution",
        // 章节分布按 token 加权归一，堆积和为 1
        data: chapterEntries.map((chapter) => chapter.distribution?.[topicId]?.weight ?? 0),
        barMaxWidth: 26,
      })),
    };
  }, [view, distribution, chapters, primaryColor]);

  const hasBookData = distribution != null && distribution.length > 0;
  const hasChapterData = chapters.some((chapter) => chapter.distribution != null && chapter.distribution.length > 0);

  return (
    <div className={`flex h-full min-h-0 flex-col gap-2 ${className ?? ""}`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-text">完整主题分布</span>
        <div className="flex gap-1 rounded-lg border border-border/60 p-0.5 text-xs">
          {(
            [
              ["book", "全书"],
              ["chapter", "章节"],
            ] as [DistributionView, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              disabled={(value === "book" && !hasBookData) || (value === "chapter" && !hasChapterData)}
              onClick={() => setView(value)}
              className={`rounded-md px-2 py-0.5 transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                view === value ? "bg-primary-subtle text-primary" : "text-text-muted hover:text-text"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-[240px] flex-1">
        <ReactEChartsCore key={themeSignature} option={option} notMerge style={{ height: "100%", width: "100%" }} />
      </div>
    </div>
  );
}
