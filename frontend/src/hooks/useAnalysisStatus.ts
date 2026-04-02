import { useQuery } from "@tanstack/react-query";
import { getAnalysisStatus } from "@/api/analysis";

/**
 * Poll analysis task status at a configurable interval.
 * Stops polling once the task reaches a terminal state.
 */
export function useAnalysisStatus(
  novelId: string | null,
  taskId: string | null,
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: ["analysis-status", novelId, taskId],
    queryFn: () => getAnalysisStatus(novelId!, taskId!),
    enabled: !!novelId && !!taskId && (options?.enabled ?? true),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 3000; // Poll every 3 seconds
    },
  });
}
