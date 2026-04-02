import { useParams } from "react-router-dom";
import { RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { TaskSelector } from "./TaskSelector";
import { useNovelStore } from "@/store/novelStore";
import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";
import { cn } from "@/lib/cn";
import { taskStatusConfig } from "@/lib/utils";
import type { TaskStatus } from "@/api/types";

export interface NovelHeaderProps {
  title: string;
  novelId?: string;
  status?: TaskStatus;
  onReanalyze?: () => void;
  onDelete?: () => void;
  isReanalyzing?: boolean;
  className?: string;
}

export function NovelHeader({
  title,
  novelId: novelIdProp,
  status,
  onReanalyze,
  onDelete,
  isReanalyzing = false,
  className,
}: NovelHeaderProps) {
  const routeParams = useParams<{ novelId: string }>();
  const novelId = novelIdProp ?? routeParams.novelId;
  const { currentTaskId } = useNovelStore();

  const { data: statusData } = useAnalysisStatus(
    novelId ?? null,
    currentTaskId,
    { enabled: status === "chunking" || status === "annotating" || status === "aggregating" || status === "diagnosing" || status === "pending" }
  );

  const currentStatus = statusData?.status ?? status;
  const config = currentStatus ? taskStatusConfig[currentStatus] : undefined;

  return (
    <div className={cn("flex flex-wrap items-center gap-4", className)}>
      <h1 className="text-2xl font-bold text-text">{title}</h1>

      {config && (
        <Badge variant={config.variant}>{config.label}</Badge>
      )}

      {novelId && (
        <TaskSelector novelId={novelId} />
      )}

      <div className="ml-auto flex items-center gap-2">
        {onReanalyze && (
          <Button
            variant="outline"
            size="sm"
            onClick={onReanalyze}
            disabled={isReanalyzing}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isReanalyzing && "animate-spin")} />
            重新分析
          </Button>
        )}
        {onDelete && (
          <Button variant="ghost" size="sm" onClick={onDelete}>
            <Trash2 className="h-3.5 w-3.5" />
            删除
          </Button>
        )}
      </div>
    </div>
  );
}
