/** 展示情绪趋势曲线和节奏张力曲线，并支持 X 轴缩放同步 */
import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import ReactEChartsCore from "echarts-for-react";
import { getChunkCurves, getNarrativeStructure } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Button } from "@/components/ui/button";
import { CurveToolbar } from "@/components/charts/CurveToolbar";
import { EmotionCurveChart } from "@/components/charts/EmotionCurveChart";
import { RhythmCurveChart } from "@/components/charts/RhythmCurveChart";
import { Activity, RefreshCw } from "lucide-react";

const STALE_TIME = 5 * 60 * 1000;

type EmotionSeriesKey = "pos_density" | "neg_density" | "net_density" | "smoothed_density";
type RhythmSeriesKey = "surface_tension" | "tension_composite";

interface VisibleSeriesState {
  emotion: Set<EmotionSeriesKey>;
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
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");

  const emotionChartRef = useRef<ReactEChartsCore>(null);
  const rhythmChartRef = useRef<ReactEChartsCore>(null);

  const [visibleSeries, setVisibleSeries] = useState<VisibleSeriesState>({
    emotion: new Set<EmotionSeriesKey>(["pos_density", "neg_density", "net_density", "smoothed_density"]),
    rhythm: new Set<RhythmSeriesKey>(["surface_tension", "tension_composite"]),
  });

  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null);

  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  useEffect(() => {
    if (currentTaskId && searchParams.get("task_id") !== currentTaskId) {
      navigate(`/novels/${novelId}/curves?task_id=${currentTaskId}`, { replace: true });
    }
  }, [currentTaskId, novelId, navigate, searchParams]);

  const enabled = !!novelId && !!currentTaskId;

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

  const novelQuery = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: STALE_TIME,
  });

  const novelTitle = novelQuery.data?.title ?? "小说详情";

  const curvesData = curvesQuery.data ?? [];
  const narrativeData = narrativeQuery.data;

  const handleEmotionSeriesToggle = useCallback((newSet: Set<string>) => {
    setVisibleSeries((prev) => ({
      ...prev,
      emotion: newSet as Set<EmotionSeriesKey>,
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

  const handleZoomIn = useCallback(() => {
    const chart = emotionChartRef.current?.getEchartsInstance();
    if (!chart) return;
    const option = chart.getOption() as { dataZoom: Array<{ start: number; end: number }> };
    if (!option.dataZoom?.[0]) return;
    const { start, end } = option.dataZoom[0];
    const range = end - start;
    const newRange = Math.max(range * 0.8, 5);
    const center = (start + end) / 2;
    const newStart = Math.max(0, center - newRange / 2);
    const newEnd = Math.min(100, center + newRange / 2);
    chart.dispatchAction({
      type: "dataZoom",
      start: newStart,
      end: newEnd,
    });
  }, []);

  const handleZoomOut = useCallback(() => {
    const chart = emotionChartRef.current?.getEchartsInstance();
    if (!chart) return;
    const option = chart.getOption() as { dataZoom: Array<{ start: number; end: number }> };
    if (!option.dataZoom?.[0]) return;
    const { start, end } = option.dataZoom[0];
    const range = end - start;
    const newRange = Math.min(range * 1.25, 100);
    const center = (start + end) / 2;
    const newStart = Math.max(0, center - newRange / 2);
    const newEnd = Math.min(100, center + newRange / 2);
    chart.dispatchAction({
      type: "dataZoom",
      start: newStart,
      end: newEnd,
    });
  }, []);

  const handleReset = useCallback(() => {
    setZoomRange(null);
    const emotionChart = emotionChartRef.current?.getEchartsInstance();
    const rhythmChart = rhythmChartRef.current?.getEchartsInstance();
    emotionChart?.dispatchAction({
      type: "dataZoom",
      start: 0,
      end: 100,
    });
    rhythmChart?.dispatchAction({
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
    curvesQuery.refetch();
    narrativeQuery.refetch();
  }, [curvesQuery, narrativeQuery]);

  const isLoading = curvesQuery.isLoading || narrativeQuery.isLoading;
  const isError = curvesQuery.isError || narrativeQuery.isError;

  if (!currentTaskId) {
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
              <CurveToolbar
                onZoomIn={handleZoomIn}
                onZoomOut={handleZoomOut}
                onReset={handleReset}
                onFullscreen={() => handleFullscreen("emotion")}
                disabled={isLoading || isError || curvesData.length === 0}
              />
            }
          >
            <div className="min-h-[320px] flex-1 rounded-2xl border border-border/60 bg-surface/70 p-4">
              {isLoading ? (
                <div className="h-full w-full animate-pulse rounded bg-surface-hover" />
              ) : isError ? (
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
                <EmotionCurveChart
                  ref={emotionChartRef}
                  data={curvesData}
                  visibleSeries={visibleSeries.emotion}
                  onSeriesToggle={handleEmotionSeriesToggle}
                  zoomRange={zoomRange}
                  onZoomChange={handleZoomChange}
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
                onZoomIn={handleZoomIn}
                onZoomOut={handleZoomOut}
                onReset={handleReset}
                onFullscreen={() => handleFullscreen("rhythm")}
                disabled={isLoading || isError || curvesData.length === 0}
              />
            }
          >
            <div className="min-h-[320px] flex-1 rounded-2xl border border-border/60 bg-surface/70 p-4">
              {isLoading ? (
                <div className="h-full w-full animate-pulse rounded bg-surface-hover" />
              ) : isError ? (
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
