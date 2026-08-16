/** 展示情绪趋势窗口聚合曲线和节奏张力曲线，并支持 X 轴缩放同步 */
import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import ReactEChartsCore from "echarts-for-react";
import { getParagraphCurves, getEmotionTrend, getNarrativeStructure } from "@/api/results";
import { getNovel } from "@/api/novels";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { useNovelScopedTask, shouldWriteBackTaskUrl } from "@/hooks/useNovelScopedTask";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CurveToolbar } from "@/components/charts/CurveToolbar";
import { EmotionTrendChart, type EmotionTrendSeriesKey } from "@/components/charts/EmotionTrendChart";
import { RhythmCurveChart } from "@/components/charts/RhythmCurveChart";
import { Activity, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import type { EmotionTrendWindow } from "@/api/types";

const STALE_TIME = 5 * 60 * 1000;
const ZOOM_REFETCH_DEBOUNCE_MS = 300;

type RhythmSeriesKey = "surface_tension" | "smoothed_surface_tension";

const WINDOW_COUNT_OPTIONS = [5, 10, 20, 40] as const;
const DEFAULT_WINDOW_COUNT = 20;

interface VisibleSeriesState {
  emotion: Set<EmotionTrendSeriesKey>;
  rhythm: Set<RhythmSeriesKey>;
}

/**
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：曲线页改为情绪优先的 tab 工作台，避免两张大图上下堆叠超出屏幕高度
 */
export function CurvesPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const urlTaskId = searchParams.get("task_id");

  // 2026-08-13 P1-2: 小说作用域任务守卫——跨小说切换后旧小说的任务
  // 不得用于新小说的查询，也不得回写固化成新小说 URL（模式同 GraphPage）
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTaskId);

  const emotionChartRef = useRef<ReactEChartsCore>(null);
  const rhythmChartRef = useRef<ReactEChartsCore>(null);

  const [visibleSeries, setVisibleSeries] = useState<VisibleSeriesState>({
    emotion: new Set<EmotionTrendSeriesKey>([
      "pooled_pos_density",
      "pooled_neg_density",
      "pooled_net_density",
      "smoothed_pooled_net_density",
    ]),
    rhythm: new Set<RhythmSeriesKey>(["surface_tension", "smoothed_surface_tension"]),
  });

  // M4：zoomRange 语义从"分块索引对"改为"position 数值对"（值域 [0,1]），
  // 图表内按 zoomRange[0]/1*100 换算 dataZoom 百分比
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null);

  // 窗口粒度切换：情绪 tab 以每窗段落数控制展示粒度，默认每窗 20 段
  const [windowParagraphs, setWindowParagraphs] = useState<number>(DEFAULT_WINDOW_COUNT);

  // 仅在 datazoomend 后提交聚合区间，拖拽过程中保持当前窗口数据
  const [trendRange, setTrendRange] = useState<[number, number] | null>(null);
  const trendRangeTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (trendRangeTimerRef.current !== null) {
        window.clearTimeout(trendRangeTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!novelId || !storeTaskId) return;
    if (!shouldWriteBackTaskUrl(urlTaskId, storeTaskId, urlTaskSyncRef)) return;
    navigate(`/novels/${novelId}/curves?task_id=${storeTaskId}`, { replace: true });
  }, [navigate, novelId, storeTaskId, urlTaskId, urlTaskSyncRef]);

  const enabled = !!novelId && !!storeTaskId;

  const emotionTrendQuery = useQuery({
    queryKey: ["emotion-trend", novelId, storeTaskId, windowParagraphs, trendRange],
    queryFn: () =>
      getEmotionTrend(novelId!, storeTaskId!, {
        windowParagraphs,
        ...(trendRange && { range: trendRange }),
      }),
    enabled,
    staleTime: STALE_TIME,
    placeholderData: keepPreviousData,
  });

  const curvesQuery = useQuery({
    queryKey: ["paragraph-curves", novelId, storeTaskId],
    queryFn: () => getParagraphCurves(novelId!, storeTaskId!, { maxPoints: 800 }),
    enabled,
    staleTime: STALE_TIME,
  });

  const narrativeQuery = useQuery({
    queryKey: ["metrics", novelId, storeTaskId, "narrative"],
    queryFn: () => getNarrativeStructure(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const novelQuery = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: STALE_TIME,
  });

  const novelTitle = novelQuery.data?.title ?? "小说详情";

  const emotionData = emotionTrendQuery.data ?? [];
  const curvesData = curvesQuery.data ?? [];
  const narrativeData = narrativeQuery.data;

  const handleEmotionSeriesToggle = useCallback((newSet: Set<string>) => {
    setVisibleSeries((prev) => ({
      ...prev,
      emotion: newSet as Set<EmotionTrendSeriesKey>,
    }));
  }, []);

  const handleRhythmSeriesToggle = useCallback((newSet: Set<string>) => {
    setVisibleSeries((prev) => ({
      ...prev,
      rhythm: newSet as Set<RhythmSeriesKey>,
    }));
  }, []);

  const handleZoomChange = useCallback((range: [number, number] | null) => {
    setZoomRange(range);
  }, []);

  // 2026-08-15：datazoomend 后防抖提交当前 position 区间
  const handleEmotionZoomEnd = useCallback((range: [number, number] | null) => {
    if (trendRangeTimerRef.current !== null) {
      window.clearTimeout(trendRangeTimerRef.current);
    }
    trendRangeTimerRef.current = window.setTimeout(() => {
      const normalizedRange = range
        ? [Number(range[0].toFixed(3)), Number(range[1].toFixed(3))] as [number, number]
        : null;
      setTrendRange(
        normalizedRange && normalizedRange[0] <= 0 && normalizedRange[1] >= 1
          ? null
          : normalizedRange
      );
    }, ZOOM_REFETCH_DEBOUNCE_MS);
  }, []);

  // 点击窗口定位到窗口起始章节原文（复用 graph 页 selected_chapter 深链约定）
  const handleTrendPointClick = useCallback(
    (window: EmotionTrendWindow) => {
      if (!novelId || !storeTaskId) {
        toast.info(`该窗口位于第 ${window.chapter_start} 章 第 ${window.paragraph_start + 1} 段`);
        return;
      }
      navigate(`/novels/${novelId}/graph?task_id=${storeTaskId}&selected_chapter=${window.chapter_start}`);
    },
    [navigate, novelId, storeTaskId]
  );

  // 2026-08-14 P2-23：缩放/重置必须按 chartType 分流到当前可见图表。
  // 此前硬编码 emotionChartRef，节奏 tab 的按钮实际作用于隐藏的情绪图，
  // 可见的节奏图完全无响应（dispatchAction 不会触发 dataZoom 事件，
  // 共享 zoomRange 状态也不会更新）
  const _zoomByChartType = useCallback(
    (chartType: "emotion" | "rhythm", factor: number) => {
      const chart =
        chartType === "emotion"
          ? emotionChartRef.current?.getEchartsInstance()
          : rhythmChartRef.current?.getEchartsInstance();
      if (!chart) return;
      const option = chart.getOption() as { dataZoom: Array<{ start: number; end: number }> };
      if (!option.dataZoom?.[0]) return;
      const { start, end } = option.dataZoom[0];
      const range = end - start;
      const newRange = factor < 1 ? Math.max(range * factor, 5) : Math.min(range * factor, 100);
      const center = (start + end) / 2;
      const newStart = Math.max(0, center - newRange / 2);
      const newEnd = Math.min(100, center + newRange / 2);
      chart.dispatchAction({
        type: "dataZoom",
        start: newStart,
        end: newEnd,
      });
    },
    []
  );

  const handleZoomIn = useCallback(
    (chartType: "emotion" | "rhythm") => {
      _zoomByChartType(chartType, 0.8);
    },
    [_zoomByChartType]
  );

  const handleZoomOut = useCallback(
    (chartType: "emotion" | "rhythm") => {
      _zoomByChartType(chartType, 1.25);
    },
    [_zoomByChartType]
  );

  const handleReset = useCallback((chartType: "emotion" | "rhythm") => {
    setZoomRange(null);
    const chart =
      chartType === "emotion"
        ? emotionChartRef.current?.getEchartsInstance()
        : rhythmChartRef.current?.getEchartsInstance();
    chart?.dispatchAction({
      type: "dataZoom",
      start: 0,
      end: 100,
    });
  }, []);

  const handleFullscreen = useCallback((chartType: "emotion" | "rhythm") => {
    const chart = chartType === "emotion" 
      ? emotionChartRef.current?.getEchartsInstance()
      : rhythmChartRef.current?.getEchartsInstance();
    if (!chart) return;
    const dom = chart.getDom();
    if (dom.requestFullscreen) {
      dom.requestFullscreen();
    }
  }, []);

  const handleRetry = useCallback(() => {
    emotionTrendQuery.refetch();
    curvesQuery.refetch();
    narrativeQuery.refetch();
  }, [emotionTrendQuery, curvesQuery, narrativeQuery]);

  // 情绪 tab（窗口聚合）与节奏 tab（段落张力）各自独立的加载/错误态
  const emotionLoading = emotionTrendQuery.isLoading;
  const emotionNotComplete = isAnalysisNotCompleteError(emotionTrendQuery.error);
  const emotionFailed = getAnalysisNotCompleteRunStatus(emotionTrendQuery.error) === "failed";
  const emotionError = emotionTrendQuery.isError && !emotionNotComplete;

  const rhythmLoading = curvesQuery.isLoading || narrativeQuery.isLoading;
  const rhythmNotComplete =
    isAnalysisNotCompleteError(curvesQuery.error) || isAnalysisNotCompleteError(narrativeQuery.error);
  const rhythmFailed =
    getAnalysisNotCompleteRunStatus(curvesQuery.error) === "failed" ||
    getAnalysisNotCompleteRunStatus(narrativeQuery.error) === "failed";
  const rhythmError = (curvesQuery.isError || narrativeQuery.isError) && !rhythmNotComplete;

  if (!storeTaskId) {
    return (
      <AnalysisWorkspace title={novelTitle}>
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">请先选择分析任务</h3>
            <p className="mt-1 text-sm text-text-muted">
              使用顶部任务选择器选择一个已完成的任务以查看曲线
            </p>
          </div>
        </div>
      </AnalysisWorkspace>
    );
  }

  return (
    <AnalysisWorkspace title={novelTitle}>
      {/*
        2026-04-28，任务：分析详情页单屏 Tabs 改造
        修改原因：曲线页从上下堆叠改为 tab，默认展示最重要的情绪趋势，图表由单屏工作区统一约束。
      */}
      <AnalysisWorkspace.Tabs defaultValue="emotion">
        <AnalysisWorkspace.Tab value="emotion" label="情绪趋势">
          <DashboardCardShell
            title="情绪趋势曲线"
            icon={<Activity className="h-4 w-4" />}
            accent="primary"
            showOrb
            className="h-full"
            contentClassName="flex h-full flex-col"
            bodyClassName="min-h-0 flex-1 gap-3"
            headerRight={
              <div className="flex items-center gap-2">
                <Select
                  value={String(windowParagraphs)}
                  onValueChange={(value) => setWindowParagraphs(Number(value))}
                >
                  <SelectTrigger className="h-8 w-[112px]" aria-label="窗口粒度">
                    <SelectValue placeholder="窗口粒度" />
                  </SelectTrigger>
                  <SelectContent>
                    {WINDOW_COUNT_OPTIONS.map((count) => (
                      <SelectItem key={count} value={String(count)}>
                        每窗 {count} 段
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <CurveToolbar
                  onZoomIn={() => handleZoomIn("emotion")}
                  onZoomOut={() => handleZoomOut("emotion")}
                  onReset={() => handleReset("emotion")}
                  onFullscreen={() => handleFullscreen("emotion")}
                  disabled={emotionLoading || emotionError || emotionData.length === 0}
                />
              </div>
            }
          >
            <div className="min-h-[320px] flex-1 rounded-2xl border border-border/60 bg-surface/70 p-4">
              {emotionLoading ? (
                <div className="h-full w-full animate-pulse rounded bg-surface-hover" />
              ) : emotionNotComplete ? (
                <AnalysisNotCompleteState
                  title={emotionFailed ? "曲线分析任务已失败" : "曲线结果尚未完成"}
                  description={
                    emotionFailed
                      ? "该分析任务已失败，曲线数据无法读取，请重新发起分析后再查看。"
                      : "当前任务仍在分析中，曲线数据暂时不可读，请等待任务进入完成态后再查看。"
                  }
                  failed={emotionFailed}
                />
              ) : emotionError ? (
                <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-text-muted">
                  <span>加载失败</span>
                  <Button variant="outline" size="sm" onClick={handleRetry} className="gap-2">
                    <RefreshCw className="h-4 w-4" />
                    重试
                  </Button>
                </div>
              ) : emotionData.length === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-text-muted">暂无曲线数据</div>
              ) : (
                <EmotionTrendChart
                  ref={emotionChartRef}
                  data={emotionData}
                  visibleSeries={visibleSeries.emotion}
                  onSeriesToggle={handleEmotionSeriesToggle}
                  zoomRange={zoomRange}
                  onZoomChange={handleZoomChange}
                  onZoomEnd={handleEmotionZoomEnd}
                  onPointClick={handleTrendPointClick}
                  height="100%"
                  className="h-full"
                />
              )}
            </div>
          </DashboardCardShell>
        </AnalysisWorkspace.Tab>
        <AnalysisWorkspace.Tab value="rhythm" label="节奏张力">
          <DashboardCardShell
            title="节奏张力曲线"
            icon={<Activity className="h-4 w-4" />}
            accent="chart-3"
            className="h-full"
            contentClassName="flex h-full flex-col"
            bodyClassName="min-h-0 flex-1 gap-3"
            headerRight={
              <CurveToolbar
                onZoomIn={() => handleZoomIn("rhythm")}
                onZoomOut={() => handleZoomOut("rhythm")}
                onReset={() => handleReset("rhythm")}
                onFullscreen={() => handleFullscreen("rhythm")}
                disabled={rhythmLoading || rhythmError || curvesData.length === 0}
              />
            }
          >
            <div className="min-h-[320px] flex-1 rounded-2xl border border-border/60 bg-surface/70 p-4">
              {rhythmLoading ? (
                <div className="h-full w-full animate-pulse rounded bg-surface-hover" />
              ) : rhythmNotComplete ? (
                <AnalysisNotCompleteState
                  title={rhythmFailed ? "曲线分析任务已失败" : "曲线结果尚未完成"}
                  description={
                    rhythmFailed
                      ? "该分析任务已失败，曲线数据无法读取，请重新发起分析后再查看。"
                      : "当前任务仍在分析中，曲线数据暂时不可读，请等待任务进入完成态后再查看。"
                  }
                  failed={rhythmFailed}
                />
              ) : rhythmError ? (
                <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-text-muted">
                  <span>加载失败</span>
                  <Button variant="outline" size="sm" onClick={handleRetry} className="gap-2">
                    <RefreshCw className="h-4 w-4" />
                    重试
                  </Button>
                </div>
              ) : curvesData.length === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-text-muted">暂无曲线数据</div>
              ) : (
                <RhythmCurveChart
                  ref={rhythmChartRef}
                  data={curvesData}
                  narrativeStructure={narrativeData}
                  visibleSeries={visibleSeries.rhythm}
                  onSeriesToggle={handleRhythmSeriesToggle}
                  zoomRange={zoomRange}
                  onZoomChange={handleZoomChange}
                  height="100%"
                  className="h-full"
                />
              )}
            </div>
          </DashboardCardShell>
        </AnalysisWorkspace.Tab>
      </AnalysisWorkspace.Tabs>
    </AnalysisWorkspace>
  );
}
