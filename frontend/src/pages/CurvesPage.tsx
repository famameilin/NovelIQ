/** 展示情绪趋势曲线和节奏张力曲线，并支持 X 轴缩放同步 */
import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import ReactEChartsCore from "echarts-for-react";
import { getParagraphCurves, getNarrativeStructure } from "@/api/results";
import { getNovel } from "@/api/novels";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { useNovelScopedTask, shouldWriteBackTaskUrl } from "@/hooks/useNovelScopedTask";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { Button } from "@/components/ui/button";
import { CurveToolbar } from "@/components/charts/CurveToolbar";
import { EmotionCurveChart } from "@/components/charts/EmotionCurveChart";
import { RhythmCurveChart } from "@/components/charts/RhythmCurveChart";
import { Activity, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import type { ParagraphCurvePoint } from "@/api/types";

const STALE_TIME = 5 * 60 * 1000;

type EmotionSeriesKey = "pos_density" | "neg_density" | "net_density" | "smoothed_net_density";
type RhythmSeriesKey = "surface_tension" | "smoothed_surface_tension";

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

  const urlTaskId = searchParams.get("task_id");

  // 2026-08-13 P1-2: 小说作用域任务守卫——跨小说切换后旧小说的任务
  // 不得用于新小说的查询，也不得回写固化成新小说 URL（模式同 GraphPage）
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTaskId);

  const emotionChartRef = useRef<ReactEChartsCore>(null);
  const rhythmChartRef = useRef<ReactEChartsCore>(null);

  const [visibleSeries, setVisibleSeries] = useState<VisibleSeriesState>({
    emotion: new Set<EmotionSeriesKey>(["pos_density", "neg_density", "net_density", "smoothed_net_density"]),
    rhythm: new Set<RhythmSeriesKey>(["surface_tension", "smoothed_surface_tension"]),
  });

  // M4：zoomRange 语义从"分块索引对"改为"position 数值对"（值域 [0,1]），
  // 图表内按 zoomRange[0]/1*100 换算 dataZoom 百分比
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null);

  useEffect(() => {
    if (!novelId || !storeTaskId) return;
    if (!shouldWriteBackTaskUrl(urlTaskId, storeTaskId, urlTaskSyncRef)) return;
    navigate(`/novels/${novelId}/curves?task_id=${storeTaskId}`, { replace: true });
  }, [navigate, novelId, storeTaskId, urlTaskId, urlTaskSyncRef]);

  const enabled = !!novelId && !!storeTaskId;

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

  // M4 §14.4：点击曲线点定位到对应章节原文（复用 graph 页 selected_chunk 深链约定）；
  // 无任务上下文时仅提示章节位置，不跳转
  const handlePointClick = useCallback(
    (point: ParagraphCurvePoint) => {
      if (!novelId || !storeTaskId) {
        toast.info(`该段位于第 ${point.chapter_id} 章 第 ${point.paragraph_index + 1} 段`);
        return;
      }
      navigate(`/novels/${novelId}/graph?task_id=${storeTaskId}&selected_chunk=${point.chapter_id}`);
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
    curvesQuery.refetch();
    narrativeQuery.refetch();
  }, [curvesQuery, narrativeQuery]);

  const isLoading = curvesQuery.isLoading || narrativeQuery.isLoading;
  const isAnalysisNotComplete =
    isAnalysisNotCompleteError(curvesQuery.error) || isAnalysisNotCompleteError(narrativeQuery.error);
  const analysisFailed =
    getAnalysisNotCompleteRunStatus(curvesQuery.error) === "failed" ||
    getAnalysisNotCompleteRunStatus(narrativeQuery.error) === "failed";
  const isError = (curvesQuery.isError || narrativeQuery.isError) && !isAnalysisNotComplete;

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
              <CurveToolbar
                onZoomIn={() => handleZoomIn("emotion")}
                onZoomOut={() => handleZoomOut("emotion")}
                onReset={() => handleReset("emotion")}
                onFullscreen={() => handleFullscreen("emotion")}
                disabled={isLoading || isError || curvesData.length === 0}
              />
            }
          >
            <div className="min-h-[320px] flex-1 rounded-2xl border border-border/60 bg-surface/70 p-4">
              {isLoading ? (
                <div className="h-full w-full animate-pulse rounded bg-surface-hover" />
              ) : isAnalysisNotComplete ? (
                <AnalysisNotCompleteState
                  title={analysisFailed ? "曲线分析任务已失败" : "曲线结果尚未完成"}
                  description={
                    analysisFailed
                      ? "该分析任务已失败，曲线数据无法读取，请重新发起分析后再查看。"
                      : "当前任务仍在分析中，曲线数据暂时不可读，请等待任务进入完成态后再查看。"
                  }
                  failed={analysisFailed}
                />
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
                  onPointClick={handlePointClick}
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
                disabled={isLoading || isError || curvesData.length === 0}
              />
            }
          >
            <div className="min-h-[320px] flex-1 rounded-2xl border border-border/60 bg-surface/70 p-4">
              {isLoading ? (
                <div className="h-full w-full animate-pulse rounded bg-surface-hover" />
              ) : isAnalysisNotComplete ? (
                <AnalysisNotCompleteState
                  title={analysisFailed ? "曲线分析任务已失败" : "曲线结果尚未完成"}
                  description={
                    analysisFailed
                      ? "该分析任务已失败，曲线数据无法读取，请重新发起分析后再查看。"
                      : "当前任务仍在分析中，曲线数据暂时不可读，请等待任务进入完成态后再查看。"
                  }
                  failed={analysisFailed}
                />
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
