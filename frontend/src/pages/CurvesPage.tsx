/**
 * CurvesPage - 情绪/节奏曲线页面
 * 
 * 创建时间: 2026-04-04
 * 创建者: AI Assistant
 * 任务: Phase 1-D 情绪/节奏曲线
 * 说明: 展示情绪趋势曲线和节奏张力曲线，支持 X 轴缩放同步
 * 
 * 修改时间: 2026-04-04
 * 修改者: AI Assistant
 * 修改内容: 
 *   - 重构为使用 EmotionCurveChart 和 RhythmCurveChart 组件
 *   - 集成 CurveToolbar 工具栏
 *   - 删除未使用的 SkeletonCard 函数
 *   - 添加错误重试机制
 *   - 优化 URL 同步 useEffect，避免重复导航
 *   - 统一 borderColor 获取方式
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import ReactEChartsCore from "echarts-for-react";
import { getChunkCurves, getNarrativeStructure } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CurveToolbar } from "@/components/charts/CurveToolbar";
import { EmotionCurveChart } from "@/components/charts/EmotionCurveChart";
import { RhythmCurveChart } from "@/components/charts/RhythmCurveChart";
import { RefreshCw } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const STALE_TIME = 5 * 60 * 1000;

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

type EmotionSeriesKey = "pos_density" | "neg_density" | "net_density" | "smoothed_density";
type RhythmSeriesKey = "surface_tension" | "tension_composite";

interface VisibleSeriesState {
  emotion: Set<EmotionSeriesKey>;
  rhythm: Set<RhythmSeriesKey>;
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
      <PageContainer>
        <NovelHeader title={novelTitle} />
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
      <NovelHeader title={novelTitle} />

      <div className="space-y-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold text-text">
              情绪趋势曲线
                </CardTitle>
                <CurveToolbar
                  onZoomIn={handleZoomIn}
                  onZoomOut={handleZoomOut}
                  onReset={handleReset}
                  onFullscreen={() => handleFullscreen("emotion")}
                  disabled={isLoading || isError || curvesData.length === 0}
                />
              </div>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="h-[350px] w-full animate-pulse rounded bg-surface-hover" />
              ) : isError ? (
                <div className="flex h-[350px] flex-col items-center justify-center gap-3 text-sm text-text-muted">
                  <span>加载失败</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleRetry}
                    className="gap-2"
                  >
                    <RefreshCw className="h-4 w-4" />
                    重试
                  </Button>
                </div>
              ) : curvesData.length === 0 ? (
                <div className="flex h-[350px] items-center justify-center text-sm text-text-muted">
                  暂无曲线数据
                </div>
              ) : (
                <EmotionCurveChart
                  ref={emotionChartRef}
                  data={curvesData}
                  visibleSeries={visibleSeries.emotion}
                  onSeriesToggle={handleEmotionSeriesToggle}
                  zoomRange={zoomRange}
                  onZoomChange={handleZoomChange}
                  height={350}
                />
              )}
            </CardContent>
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold text-text">
                  节奏张力曲线
                </CardTitle>
                <CurveToolbar
                  onZoomIn={handleZoomIn}
                  onZoomOut={handleZoomOut}
                  onReset={handleReset}
                  onFullscreen={() => handleFullscreen("rhythm")}
                  disabled={isLoading || isError || curvesData.length === 0}
                />
              </div>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="h-[350px] w-full animate-pulse rounded bg-surface-hover" />
              ) : isError ? (
                <div className="flex h-[350px] flex-col items-center justify-center gap-3 text-sm text-text-muted">
                  <span>加载失败</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleRetry}
                    className="gap-2"
                  >
                    <RefreshCw className="h-4 w-4" />
                    重试
                  </Button>
                </div>
              ) : curvesData.length === 0 ? (
                <div className="flex h-[350px] items-center justify-center text-sm text-text-muted">
                  暂无曲线数据
                </div>
              ) : (
                <RhythmCurveChart
                  ref={rhythmChartRef}
                  data={curvesData}
                  narrativeStructure={narrativeData}
                  visibleSeries={visibleSeries.rhythm}
                  onSeriesToggle={handleRhythmSeriesToggle}
                  zoomRange={zoomRange}
                  onZoomChange={handleZoomChange}
                  height={350}
                />
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </PageContainer>
  );
}
