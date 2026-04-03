import { useEffect } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  getNarrativeStructure,
  getEmotionStats,
  getCharacterStats,
  getStyleStats,
  getCultureStats,
  getDiagnosis,
  getChunkCurves,
} from "@/api/results";
import { useNovelStore } from "@/store/novelStore";
import { useThemeStore } from "@/store/themeStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { FiveDimensionRadar } from "@/components/charts/FiveDimensionRadar";
import { DiagnosisSummaryCard } from "@/components/common/DiagnosisSummaryCard";
import { MetricCardGrid } from "@/components/common/MetricCardGrid";
import { MiniCurvePreview } from "@/components/charts/MiniCurvePreview";
import { toRadarDimensions } from "@/lib/normalize";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DEFAULT_SEED } from "@/store/themeStore";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const STALE_TIME = 5 * 60 * 1000;

/* ------------------------------------------------------------------ */
/*  Skeleton                                                          */
/* ------------------------------------------------------------------ */

function SkeletonGrid() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="h-[300px]">
          <div className="flex h-full items-center justify-center">
            <div className="h-48 w-48 animate-pulse rounded-full bg-surface-hover" />
          </div>
        </Card>
        <Card className="h-[300px]">
          <CardContent className="p-5">
            <div className="space-y-4">
              <div className="h-5 w-24 animate-pulse rounded bg-surface-hover" />
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex gap-3">
                    <div className="h-4 w-4 animate-pulse rounded bg-surface-hover" />
                    <div className="h-4 flex-1 animate-pulse rounded bg-surface-hover" />
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="h-[120px]" />
        ))}
      </div>
      <Card className="h-[200px]" />
    </div>
  );
}

function EmptyTaskPrompt() {
  return (
    <div className="flex h-96 flex-col items-center justify-center gap-4">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary-subtle">
        <svg className="h-8 w-8 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
        </svg>
      </div>
      <div className="text-center">
        <h3 className="text-lg font-semibold text-text">请选择分析任务</h3>
        <p className="mt-1 text-sm text-text-muted">
          使用顶部任务选择器选择一个已完成的任务以查看分析结果
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

export function NovelDetailPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentTaskId, setNovel, setTask } = useNovelStore();
  const { setSeedColor } = useThemeStore();

  const urlTaskId = searchParams.get("task_id");

  // Sync novelId to store on mount; initialize task from URL if present
  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId && urlTaskId !== currentTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, currentTaskId, setNovel, setTask]);

  // Reflect currentTaskId to URL for shareability
  useEffect(() => {
    if (currentTaskId) {
      navigate(`/novels/${novelId}?task_id=${currentTaskId}`, { replace: true });
    }
  }, [currentTaskId, novelId, navigate]);

  // Parallel data fetching
  const enabled = !!novelId && !!currentTaskId;

  const narrativeQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "narrative"],
    queryFn: () => getNarrativeStructure(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const emotionQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "emotion"],
    queryFn: () => getEmotionStats(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const characterQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "character"],
    queryFn: () => getCharacterStats(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const styleQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "style"],
    queryFn: () => getStyleStats(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const cultureQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "culture"],
    queryFn: () => getCultureStats(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const curvesQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "curves"],
    queryFn: () => getChunkCurves(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  // Apply theme_color from diagnosis when available (declared after diagnosisQuery)
  useEffect(() => {
    if (diagnosisQuery.data?.theme_color && HEX_COLOR_RE.test(diagnosisQuery.data.theme_color)) {
      setSeedColor(diagnosisQuery.data.theme_color);
    } else if (!diagnosisQuery.isLoading && !diagnosisQuery.data) {
      setSeedColor(DEFAULT_SEED);
    }
  }, [diagnosisQuery.data, diagnosisQuery.isLoading, setSeedColor]);

  const allMetricsLoaded =
    narrativeQuery.data &&
    emotionQuery.data &&
    characterQuery.data &&
    styleQuery.data &&
    cultureQuery.data;

  const isLoading =
    enabled &&
    (narrativeQuery.isLoading ||
      emotionQuery.isLoading ||
      characterQuery.isLoading ||
      styleQuery.isLoading ||
      cultureQuery.isLoading ||
      diagnosisQuery.isLoading ||
      curvesQuery.isLoading);

  const hasAnyError =
    narrativeQuery.isError ||
    emotionQuery.isError ||
    characterQuery.isError ||
    styleQuery.isError ||
    cultureQuery.isError ||
    diagnosisQuery.isError ||
    curvesQuery.isError;

  const retryAll = () => {
    narrativeQuery.refetch();
    emotionQuery.refetch();
    characterQuery.refetch();
    styleQuery.refetch();
    cultureQuery.refetch();
    diagnosisQuery.refetch();
    curvesQuery.refetch();
  };

  // ---------- Render ----------

  return (
    <PageContainer>
      {/* Header */}
      <NovelHeader
        title={diagnosisQuery.data?.narrative_type ? `${diagnosisQuery.data.narrative_type}分析` : (novelId ? `小说 ${novelId.slice(0, 8)}` : "小说分析")}
        status={diagnosisQuery.data ? "completed" : undefined}
        className="mb-6"
      />

      {/* No task selected */}
      {!currentTaskId && <EmptyTaskPrompt />}

      {/* Loading skeleton */}
      {isLoading && currentTaskId && <SkeletonGrid />}

      {/* Error state — check all queries */}
      {hasAnyError && !isLoading && currentTaskId && (
        <div className="flex h-64 flex-col items-center justify-center gap-3">
          <p className="text-sm text-text-muted">数据加载失败</p>
          <Button variant="ghost" size="sm" onClick={retryAll}>
            重试
          </Button>
        </div>
      )}

      {/* Main content */}
      {allMetricsLoaded && !isLoading && currentTaskId && (
        <div className="space-y-6">
          {/* Row 1: Radar + Diagnosis Summary */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card className="p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">五维指标概览</h3>
              <FiveDimensionRadar
                dimensions={toRadarDimensions({
                  narrative: narrativeQuery.data,
                  emotion: emotionQuery.data,
                  character: characterQuery.data,
                  style: styleQuery.data,
                  culture: cultureQuery.data,
                })}
                className="h-[260px]"
              />
            </Card>

            {diagnosisQuery.data ? (
              <DiagnosisSummaryCard
                diagnosis={diagnosisQuery.data}
                novelId={novelId!}
                className="h-full"
              />
            ) : (
              <Card className="flex h-full items-center justify-center">
                <p className="text-sm text-text-muted">暂无诊断数据</p>
              </Card>
            )}
          </div>

          {/* Row 2: Metric Cards Grid */}
          <MetricCardGrid
            narrative={narrativeQuery.data}
            emotion={emotionQuery.data}
            character={characterQuery.data}
            style={styleQuery.data}
            culture={cultureQuery.data}
          />

          {/* Row 3: Mini Curve Preview */}
          <MiniCurvePreview
            data={curvesQuery.data ?? []}
            novelId={novelId!}
          />
        </div>
      )}
    </PageContainer>
  );
}
