import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { getNovel } from "@/api/novels";

const STALE_TIME = 5 * 60 * 1000;

/** 分析页标题统一取当前小说书名，书名未到达前用页面名占位 */
export function useNovelTitle(fallback: string): string {
  const { novelId } = useParams<{ novelId: string }>();
  const { data } = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: STALE_TIME,
  });
  return data?.title ?? fallback;
}
