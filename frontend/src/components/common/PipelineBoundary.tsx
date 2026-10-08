import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getPipelineSnapshot } from "@/api/pipeline";
import { useNovelStore } from "@/store/novelStore";

const caseStateLabels = { pending: "未确定", resolved: "已确定", deferred: "未确定", contested: "互斥判断" };
export function PipelineBoundary() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const currentNovelId = useNovelStore((state) => state.currentNovelId);
  const currentTaskId = useNovelStore((state) => state.currentTaskId);
  const taskId = searchParams.get("task_id") ?? (currentNovelId === novelId ? currentTaskId : null);
  const { data } = useQuery({
    queryKey: ["pipeline", novelId, taskId],
    queryFn: () => getPipelineSnapshot(novelId!, taskId!),
    enabled: Boolean(novelId && taskId),
    retry: false,
    staleTime: 30_000,
  });
  if (!data) return null;
  return (
    <div className="mb-2 shrink-0 border-b border-border px-3 py-2 text-xs text-muted-foreground"
      aria-label="分析可见边界">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <span>已完成 {data.completed_chapters}/{data.total_chapters} 章 · 已保存 {data.saved_work_count} 项工作</span>
        <span>案例池：未确定 {data.case_states.pending + data.case_states.deferred}
          {" · "}互斥判断 {data.case_states.contested} · 已确定 {data.case_states.resolved}</span>
      </div>
      {data.cases.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer">查看案例</summary>
          <ul className="mt-2 space-y-3">
            {data.cases.map((item) => <li key={item.case_id} className="border-t border-border pt-2">
              <p>{caseStateLabels[item.state]}</p>
              <p className="mt-1 break-words text-foreground">{item.description}</p>
            </li>)}
          </ul>
        </details>
      )}
      {data.connections.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer">查看事件关联</summary>
          <ul className="mt-2 space-y-3">
            {data.connections.map((item) => <li key={item.connection_id} className="border-t border-border pt-2">
              <p>{item.type === "main" ? "主因" : item.type === "secondary" ? "次因" : item.type === "causal" ? "因果关联" : "伏笔照应"}</p>
              <p className="mt-1 break-words text-foreground">{item.parent_description} → {item.description}</p>
            </li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
