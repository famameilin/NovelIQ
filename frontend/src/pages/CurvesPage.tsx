import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  DataZoomComponent,
  BrushComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getChunkCurves, getNarrativeStructure } from "@/api/results";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getCSSColorVar } from "@/lib/theme";
import { cn } from "@/lib/cn";
import type { ChunkCurvePoint, NarrativeStructureMetrics } from "@/api/types";

// Register ECharts components
echarts.use([
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  DataZoomComponent,
  BrushComponent,
  LineChart,
  BarChart,
  CanvasRenderer,
]);

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const STALE_TIME = 5 * 60 * 1000;

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

type SeriesKey = "pos_density" | "neg_density" | "net_density" | "smoothed_density";

interface VisibleSeriesState {
  emotion: Set<SeriesKey>;
  rhythm: Set<"tension_proxy" | "tension_composite">;
}

/* ------------------------------------------------------------------ */
/*  Skeleton                                                          */
/* ------------------------------------------------------------------ */

function SkeletonCard({ title }: { title: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[350px] w-full animate-pulse rounded bg-surface-hover" />
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function CurvesPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");

  // Refs for chart instances (for zoom sync)
  const emotionChartRef = useRef<ReactEChartsCore>(null);
  const rhythmChartRef = useRef<ReactEChartsCore>(null);

  // Visible series state
  const [visibleSeries, setVisibleSeries] = useState<VisibleSeriesState>({
    emotion: new Set<SeriesKey>(["pos_density", "neg_density", "net_density", "smoothed_density"]),
    rhythm: new Set<"tension_proxy" | "tension_composite">(["tension_proxy", "tension_composite"]),
  });

  // Brush range state (for sync)
  const [brushRange, setBrushRange] = useState<[number, number] | null>(null);

  // Sync novelId and taskId
  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  // Reflect currentTaskId to URL
  useEffect(() => {
    if (currentTaskId) {
      navigate(`/novels/${novelId}/curves?task_id=${currentTaskId}`, { replace: true });
    }
  }, [currentTaskId, novelId, navigate]);

  const enabled = !!novelId && !!currentTaskId;

  // Data queries
  const curvesQuery = useQuery({
    queryKey: ["chunk-curves", novelId, currentTaskId],
    queryFn: () => getChunkCurves(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const narrativeQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "narrative"],
    queryFn: () => getNarrativeStructure(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const curvesData = curvesQuery.data ?? [];
  const narrativeData = narrativeQuery.data;

  // Colors
  const positiveColor = getCSSColorVar("--chart-positive");
  const negativeColor = getCSSColorVar("--chart-negative");
  const chart1Color = getCSSColorVar("--chart-1");
  const chart2Color = getCSSColorVar("--chart-2");
  const chart3Color = getCSSColorVar("--chart-3");
  const primaryColor = getCSSColorVar("--primary");
  const borderColor = "hsl(var(--border))";

  // Series toggle handlers
  const handleEmotionSeriesToggle = useCallback((key: SeriesKey) => {
    setVisibleSeries((prev) => {
      const newSet = new Set(prev.emotion);
      if (newSet.has(key)) {
        newSet.delete(key);
      } else {
        newSet.add(key);
      }
      return { ...prev, emotion: newSet };
    });
  }, []);

  const handleRhythmSeriesToggle = useCallback((key: "tension_proxy" | "tension_composite") => {
    setVisibleSeries((prev) => {
      const newSet = new Set(prev.rhythm);
      if (newSet.has(key)) {
        newSet.delete(key);
      } else {
        newSet.add(key);
      }
      return { ...prev, rhythm: newSet };
    });
  }, []);

  // Emotion chart option
  const emotionOption = useMemo(() => {
    if (!curvesData.length) return {};

    const xData = curvesData.map((d) => d.chunk_id);

    const seriesConfigs = [
      { key: "pos_density" as const, name: "正面密度", color: positiveColor },
      { key: "neg_density" as const, name: "负面密度", color: negativeColor },
      { key: "net_density" as const, name: "净密度", color: chart1Color },
      { key: "smoothed_density" as const, name: "平滑密度", color: primaryColor },
    ];

    const series = seriesConfigs.map((config) => {
      const values = curvesData.map((d) => d[config.key] ?? null);
      const isActive = visibleSeries.emotion.has(config.key);

      return {
        name: config.name,
        type: "line" as const,
        data: isActive ? values : [],
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: config.color },
        emphasis: { focus: "series" as const },
        animationDuration: 800,
      };
    });

    return {
      grid: { top: 60, right: 30, bottom: 60, left: 50 },
      legend: {
        show: true,
        top: 8,
        itemGap: 16,
        textStyle: { color: "hsl(var(--text-muted))", fontSize: 11 },
        icon: "roundRect",
        data: seriesConfigs.map((s) => s.name),
      },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "cross" as const },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 11 },
      },
      dataZoom: [
        {
          type: "inside" as const,
          xAxisIndex: 0,
          start: brushRange ? (brushRange[0] / xData.length) * 100 : 0,
          end: brushRange ? (brushRange[1] / xData.length) * 100 : 100,
        },
        {
          type: "slider" as const,
          xAxisIndex: 0,
          start: brushRange ? (brushRange[0] / xData.length) * 100 : 0,
          end: brushRange ? (brushRange[1] / xData.length) * 100 : 100,
          height: 20,
          bottom: 10,
          borderColor: borderColor,
          backgroundColor: "hsl(var(--surface))",
          fillerColor: "hsl(var(--primary) / 0.1)",
          handleStyle: { color: "hsl(var(--primary))" },
          textStyle: { color: "hsl(var(--text-muted))", fontSize: 10 },
        },
      ],
      xAxis: {
        type: "category" as const,
        data: xData,
        name: "分块",
        nameLocation: "middle",
        nameGap: 30,
        nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 11 },
        axisLine: { lineStyle: { color: borderColor } },
        axisTick: { lineStyle: { color: borderColor } },
        axisLabel: { color: "hsl(var(--text-muted))", fontSize: 10 },
        boundaryGap: false,
      },
      yAxis: {
        type: "value" as const,
        name: "密度",
        nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: borderColor, opacity: 0.5 } },
        axisLabel: { color: "hsl(var(--text-muted))", fontSize: 10 },
      },
      series,
    };
  }, [curvesData, visibleSeries.emotion, positiveColor, negativeColor, chart1Color, primaryColor, brushRange, borderColor]);

  // Rhythm chart option
  const rhythmOption = useMemo(() => {
    if (!curvesData.length) return {};

    const xData = curvesData.map((d) => d.chunk_id);
    const totalChunks = xData.length;

    // Calculate three-act division lines
    const act1Ratio = narrativeData?.act1_ratio ?? 0.25;
    const act2Ratio = narrativeData?.act2_ratio ?? 0.55;

    const act1End = Math.round(totalChunks * act1Ratio);
    const act2End = Math.round(totalChunks * (act1Ratio + act2Ratio));

    // Get climax positions
    const climaxPositions = (narrativeData?.climax_positions ?? []).map(
      (ratio: number) => Math.round(totalChunks * ratio)
    );

    const seriesConfigs = [
      { key: "tension_proxy" as const, name: "张力代理", color: chart2Color },
      { key: "tension_composite" as const, name: "综合张力", color: chart3Color },
    ];

    const series = seriesConfigs.map((config) => {
      const values = curvesData.map((d) => d[config.key] ?? null);
      const isActive = visibleSeries.rhythm.has(config.key);

      // Build markLine for three-act division
      const markLineData: Array<{
        xAxis: number;
        label: { show: boolean; formatter: string; position: string; color: string; fontSize: number };
        lineStyle: { type: string; color: string; opacity: number };
      }> = [];

      if (isActive) {
        if (act1End > 0 && act1End < totalChunks) {
          markLineData.push({
            xAxis: act1End,
            label: { show: true, formatter: "第一幕", position: "start", color: "hsl(var(--text-muted))", fontSize: 10 },
            lineStyle: { type: "dashed", color: borderColor, opacity: 0.6 },
          });
        }
        if (act2End > 0 && act2End < totalChunks) {
          markLineData.push({
            xAxis: act2End,
            label: { show: true, formatter: "第二幕", position: "start", color: "hsl(var(--text-muted))", fontSize: 10 },
            lineStyle: { type: "dashed", color: borderColor, opacity: 0.6 },
          });
        }
      }

      return {
        name: config.name,
        type: "line" as const,
        data: isActive ? values : [],
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: config.color },
        emphasis: { focus: "series" as const },
        markLine: markLineData.length > 0 ? {
          symbol: "none",
          data: markLineData,
          animation: false,
        } : undefined,
        // Climax markers on first series
        markPoint: config.key === "tension_proxy" && climaxPositions.length > 0 ? {
          data: climaxPositions.map((chunkIdx) => ({
            coord: [chunkIdx, Math.max(...curvesData.map((d) => d.tension_proxy ?? 0))],
            value: "高潮",
            itemStyle: { color: chart3Color },
            symbolSize: 36,
            label: { show: true, fontSize: 8, color: "#fff" },
          })),
        } : undefined,
        animationDuration: 800,
      };
    });

    return {
      grid: { top: 60, right: 30, bottom: 60, left: 50 },
      legend: {
        show: true,
        top: 8,
        itemGap: 16,
        textStyle: { color: "hsl(var(--text-muted))", fontSize: 11 },
        icon: "roundRect",
        data: seriesConfigs.map((s) => s.name),
      },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "cross" as const },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 11 },
      },
      dataZoom: [
        {
          type: "inside" as const,
          xAxisIndex: 0,
          start: brushRange ? (brushRange[0] / xData.length) * 100 : 0,
          end: brushRange ? (brushRange[1] / xData.length) * 100 : 100,
        },
        {
          type: "slider" as const,
          xAxisIndex: 0,
          start: brushRange ? (brushRange[0] / xData.length) * 100 : 0,
          end: brushRange ? (brushRange[1] / xData.length) * 100 : 100,
          height: 20,
          bottom: 10,
          borderColor: borderColor,
          backgroundColor: "hsl(var(--surface))",
          fillerColor: "hsl(var(--primary) / 0.1)",
          handleStyle: { color: "hsl(var(--primary))" },
          textStyle: { color: "hsl(var(--text-muted))", fontSize: 10 },
        },
      ],
      xAxis: {
        type: "category" as const,
        data: xData,
        name: "分块",
        nameLocation: "middle",
        nameGap: 30,
        nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 11 },
        axisLine: { lineStyle: { color: borderColor } },
        axisTick: { lineStyle: { color: borderColor } },
        axisLabel: { color: "hsl(var(--text-muted))", fontSize: 10 },
        boundaryGap: false,
      },
      yAxis: {
        type: "value" as const,
        name: "张力",
        nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: borderColor, opacity: 0.5 } },
        axisLabel: { color: "hsl(var(--text-muted))", fontSize: 10 },
      },
      series,
    };
  }, [curvesData, visibleSeries.rhythm, narrativeData, chart2Color, chart3Color, brushRange, borderColor]);

  // Handle brush sync between charts
  const handleEmotionBrush = useCallback((params: { batch: Array<{ areas: Array<{ start: number; end: number }> }> }) => {
    const areas = params.batch?.[0]?.areas;
    if (areas && areas.length > 0) {
      const start = Math.round((areas[0].start / 100) * curvesData.length);
      const end = Math.round((areas[0].end / 100) * curvesData.length);
      setBrushRange([start, end]);
    } else {
      setBrushRange(null);
    }
  }, [curvesData.length]);

  // Legend click handlers
  const handleEmotionLegendClick = useCallback((params: { name: string }) => {
    const keyMap: Record<string, SeriesKey> = {
      "正面密度": "pos_density",
      "负面密度": "neg_density",
      "净密度": "net_density",
      "平滑密度": "smoothed_density",
    };
    const key = keyMap[params.name];
    if (key) handleEmotionSeriesToggle(key);
  }, [handleEmotionSeriesToggle]);

  const handleRhythmLegendClick = useCallback((params: { name: string }) => {
    const keyMap: Record<string, "tension_proxy" | "tension_composite"> = {
      "张力代理": "tension_proxy",
      "综合张力": "tension_composite",
    };
    const key = keyMap[params.name];
    if (key) handleRhythmSeriesToggle(key);
  }, [handleRhythmSeriesToggle]);

  // Loading and empty states
  const isLoading = curvesQuery.isLoading || narrativeQuery.isLoading;
  const isError = curvesQuery.isError || narrativeQuery.isError;

  if (!currentTaskId) {
    return (
      <PageContainer>
        <NovelHeader />
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">请先选择分析任务</h3>
            <p className="mt-1 text-sm text-text-muted">
              使用顶部任务选择器选择一个已完成的任务以查看曲线
            </p>
          </div>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <NovelHeader />

      <div className="space-y-6">
        {/* Emotion Curve Card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-text">
                情绪密度曲线
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="h-[350px] w-full animate-pulse rounded bg-surface-hover" />
              ) : isError ? (
                <div className="flex h-[350px] items-center justify-center text-sm text-text-muted">
                  加载失败，请重试
                </div>
              ) : curvesData.length === 0 ? (
                <div className="flex h-[350px] items-center justify-center text-sm text-text-muted">
                  暂无曲线数据
                </div>
              ) : (
                <ReactEChartsCore
                  ref={emotionChartRef}
                  echarts={echarts}
                  option={emotionOption}
                  style={{ height: "350px", width: "100%" }}
                  notMerge
                  lazyUpdate
                  onEvents={{
                   legendselectchanged: handleEmotionLegendClick,
                    datazoom: handleEmotionBrush,
                  }}
                />
              )}
            </CardContent>
          </Card>
        </motion.div>

        {/* Rhythm Curve Card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-text">
                节奏张力曲线
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="h-[350px] w-full animate-pulse rounded bg-surface-hover" />
              ) : isError ? (
                <div className="flex h-[350px] items-center justify-center text-sm text-text-muted">
                  加载失败，请重试
                </div>
              ) : curvesData.length === 0 ? (
                <div className="flex h-[350px] items-center justify-center text-sm text-text-muted">
                  暂无曲线数据
                </div>
              ) : (
                <ReactEChartsCore
                  ref={rhythmChartRef}
                  echarts={echarts}
                  option={rhythmOption}
                  style={{ height: "350px", width: "100%" }}
                  notMerge
                  lazyUpdate
                  onEvents={{
                    legendselectchanged: handleRhythmLegendClick,
                    datazoom: handleEmotionBrush,
                  }}
                />
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </PageContainer>
  );
}