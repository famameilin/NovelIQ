import { useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { getCharacters, getDiagnosis } from "@/api/results";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { CharacterRankingBar } from "@/components/charts/CharacterRankingBar";
import { RoleFunctionPie } from "@/components/charts/RoleFunctionPie";
import { CharacterTable } from "@/components/characters/CharacterTable";
import { ProtagonistCard } from "@/components/characters/ProtagonistCard";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

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
      {/* Ranking bar skeleton */}
      <Card className="h-[460px]">
        <CardContent className="p-5">
          <div className="space-y-3">
            <div className="h-5 w-28 animate-pulse rounded bg-surface-hover" />
            <div className="h-[400px] animate-pulse rounded bg-surface-hover" />
          </div>
        </CardContent>
      </Card>

      {/* Pie + Table skeleton */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="h-[340px]">
          <CardContent className="p-5">
            <div className="space-y-3">
              <div className="h-5 w-28 animate-pulse rounded bg-surface-hover" />
              <div className="h-[280px] animate-pulse rounded bg-surface-hover" />
            </div>
          </CardContent>
        </Card>
        <Card className="h-[340px]">
          <CardContent className="p-5">
            <div className="space-y-3">
              <div className="h-5 w-28 animate-pulse rounded bg-surface-hover" />
              <div className="h-[280px] animate-pulse rounded bg-surface-hover" />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function CharactersPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");

  // Sync novelId to store on mount; initialize task from URL if present
  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  // Data fetching
  const enabled = !!novelId && !!currentTaskId;

  const charactersQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "characters"],
    queryFn: () => getCharacters(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const isLoading = enabled && (charactersQuery.isLoading || diagnosisQuery.isLoading);
  const isError = enabled && (charactersQuery.isError || diagnosisQuery.isError);

  const retry = () => {
    charactersQuery.refetch();
    diagnosisQuery.refetch();
  };

  const { data: characters } = charactersQuery;
  const { data: diagnosis } = diagnosisQuery;

  // 找到主角数据
  const protagonist = characters?.find(
    (c) => c.name === diagnosis?.protagonist
  );

  // ---------- Render ----------

  return (
    <PageContainer>
      {/* Header */}
      <NovelHeader
        title="角色分析"
        status={characters ? "completed" : undefined}
        className="mb-6"
      />

      {/* Loading skeleton */}
      {isLoading && <SkeletonGrid />}

      {/* Error state */}
      {isError && !isLoading && (
        <div className="flex h-64 flex-col items-center justify-center gap-3">
          <p className="text-sm text-text-muted">数据加载失败</p>
          <Button variant="ghost" size="sm" onClick={retry}>
            重试
          </Button>
        </div>
      )}

      {/* Main content */}
      {characters && !isLoading && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="space-y-6"
        >
          {/* Character Ranking Bar */}
          <CharacterRankingBar
            characters={characters}
            protagonist={diagnosis?.protagonist}
          />

          {/* Pie + Protagonist Card */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <RoleFunctionPie characters={characters} />
            <ProtagonistCard
              protagonist={protagonist}
              protagonistName={diagnosis?.protagonist}
              arcScores={diagnosis?.arc_scores}
            />
          </div>

          {/* Character Table */}
          <CharacterTable
            characters={characters}
            protagonist={diagnosis?.protagonist}
          />
        </motion.div>
      )}
    </PageContainer>
  );
}