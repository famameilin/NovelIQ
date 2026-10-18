/**
 * TopicDistributionChart - 主题完整分布柱状图
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
import { PagedControls } from "@/components/common/PagedControls";
import { getCSSColorVar } from "@/lib/theme";
import type { ChapterTopicDistribution, TopicDistributionEntry } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, LegendComponent, BarChart, CanvasRenderer]);

interface TopicDistributionChartProps {
  distribution: TopicDistributionEntry[] | null;
  chapters: ChapterTopicDistribution[];
  className?: string;
}

type DistributionView = "book" | "chapter";
const BOOK_PAGE_SIZE = 10;
const CHAPTER_PAGE_SIZE = 9;

export function TopicDistributionChart({ distribution, chapters, className }: TopicDistributionChartProps) {
  const themeSignature = useChartThemeSignature();
  const [view, setView] = useState<DistributionView>("book");
  const [bookPage, setBookPage] = useState(1);
  const [chapterPage, setChapterPage] = useState(1);

  const primaryColor = getCSSColorVar("--chart-3");
  const bookEntries = distribution ?? [];
  const chapterEntries = chapters.filter((chapter) => chapter.distribution != null);
  const bookPageCount = Math.ceil(bookEntries.length / BOOK_PAGE_SIZE);
  const chapterPageCount = Math.ceil(chapterEntries.length / CHAPTER_PAGE_SIZE);
  const currentBookPage = Math.min(bookPage, Math.max(bookPageCount, 1));
  const currentChapterPage = Math.min(chapterPage, Math.max(chapterPageCount, 1));
  const visibleBookEntries = bookEntries.slice((currentBookPage - 1) * BOOK_PAGE_SIZE, currentBookPage * BOOK_PAGE_SIZE);
  const visibleChapters = chapterEntries.slice((currentChapterPage - 1) * CHAPTER_PAGE_SIZE, currentChapterPage * CHAPTER_PAGE_SIZE);
  const hasBookData = bookEntries.length > 0;
  const hasChapterData = chapterEntries.some((chapter) => chapter.distribution?.length);
  const activeView = !hasBookData && hasChapterData ? "chapter" : view;

  const option = useMemo(() => {
    if (activeView === "book") {
      return {
        // 全书权重通常只有几个百分点；入场动画会让首屏短暂显示成小数点后的零头。
        animation: false,
        tooltip: { trigger: "axis", valueFormatter: (value: number) => `${(value * 100).toFixed(2)}%` },
        grid: { left: 48, right: 16, top: 24, bottom: 32 },
        xAxis: {
          type: "category",
          data: visibleBookEntries.map((entry) => `主题 ${entry.topic_id + 1}`),
          axisLabel: { fontSize: 10 },
        },
        yAxis: { type: "value", axisLabel: { fontSize: 10, formatter: (value: number) => `${(value * 100).toFixed(0)}%` } },
        series: [
          {
            name: "全书权重",
            type: "bar",
            data: visibleBookEntries.map((entry) => entry.weight),
            itemStyle: { color: primaryColor, borderRadius: [3, 3, 0, 0] },
          },
        ],
      };
    }

    const topicIds = chapterEntries[0]?.distribution?.map((entry) => entry.topic_id) ?? [];
    return {
      animation: false,
      tooltip: { trigger: "item", valueFormatter: (value: number) => `${(value * 100).toFixed(2)}%` },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 10 } },
      grid: { left: 48, right: 16, top: 24, bottom: 56 },
      xAxis: {
        type: "category",
        data: visibleChapters.map((chapter) => `第${chapter.chapter_sequence}章`),
        axisLabel: { fontSize: 10 },
      },
      yAxis: {
        type: "value",
        max: (extent: { max: number }) => Math.max(1, extent.max),
        axisLabel: { fontSize: 10, formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
      },
      series: topicIds.map((topicId) => ({
        name: `主题 ${topicId + 1}`,
        type: "bar",
        stack: "distribution",
        // 章节分布按 token 加权归一，堆积和为 1
        data: visibleChapters.map((chapter) => chapter.distribution?.find((entry) => entry.topic_id === topicId)?.weight ?? null),
        barMaxWidth: 26,
      })),
    };
  }, [activeView, visibleBookEntries, visibleChapters, chapterEntries, primaryColor]);

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
                activeView === value ? "bg-primary-subtle text-primary" : "text-text-muted hover:text-text"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {(activeView === "book" ? hasBookData : hasChapterData) ? (
          <ReactEChartsCore key={themeSignature} option={option} notMerge style={{ height: "100%", width: "100%" }} />
        ) : (
          <p className="flex h-full items-center justify-center text-sm text-text-muted">暂无完整主题分布数据</p>
        )}
      </div>
      <PagedControls
        page={activeView === "book" ? currentBookPage : currentChapterPage}
        pageCount={activeView === "book" ? bookPageCount : chapterPageCount}
        onPageChange={activeView === "book" ? setBookPage : setChapterPage}
        label={activeView === "book" ? "全书主题" : "章节分布"}
      />
    </div>
  );
}
