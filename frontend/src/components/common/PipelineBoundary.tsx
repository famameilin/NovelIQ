import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getPipelineSnapshot, type PipelineAssertion } from "@/api/pipeline";
import { useNovelStore } from "@/store/novelStore";

const caseStateLabels = { pending: "未确定", resolved: "已确定", deferred: "未确定", contested: "互斥判断" };
const domainStateLabels: Record<string, string> = {
  resolved: "已关联", contested: "互斥判断", pending_dependency: "未确定",
};
const assertionLabels: Record<string, string> = {
  cross_chapter_link: "跨章关联", identity_binding: "身份关联", relation_change: "关系变化", event_link: "事件关联",
};

function assertionText(assertion: PipelineAssertion): string {
  for (const field of ["reason", "description", "name", "content", "summary"]) {
    if (typeof assertion.payload[field] === "string") return assertion.payload[field];
  }
  return JSON.stringify(assertion.payload, null, 2);
}

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
  const evidenceById = new Map(data.evidence.map((item) => [item.evidence_id, item]));
  return (
    <div className="mb-2 shrink-0 border-b border-border px-3 py-2 text-xs text-muted-foreground"
      aria-label="分析可见边界">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <span>已发布 {data.formal_count} 章</span>
        <span>案例池：未确定 {data.case_states.pending + data.case_states.deferred}
          {" · "}互斥判断 {data.case_states.contested} · 已确定 {data.case_states.resolved}</span>
      </div>
      {data.cases.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer">查看案例与证据</summary>
          <ul className="mt-2 space-y-3">
            {data.cases.map((item) => {
              const identifiers = new Set([
                ...item.source_evidence, ...item.continuity_claims.flatMap((claim) => claim.evidence_ids),
              ]);
              const evidence = [...identifiers].flatMap((identifier) => {
                const value = evidenceById.get(identifier);
                return value ? [value] : [];
              });
              return <li key={item.case_id} className="border-t border-border pt-2">
                <p className="break-words">{item.type} · {caseStateLabels[item.state]}</p>
                <p className="mt-1 break-words text-foreground">{item.description}</p>
                {item.continuity_claims.filter((claim) => typeof claim.payload.reason === "string").map((claim, index) => (
                  <p key={index} className="mt-1 break-words">{String(claim.payload.reason)}</p>
                ))}
                <ul className="mt-2 space-y-2" aria-label={`${item.description}的原文证据`}>
                  {evidence.map((value) => <li key={value.evidence_id}>
                    <span>第 {value.chapter_id} 章 · 段落 {value.paragraph_id}</span>
                    <blockquote className="mt-1 break-words border-l-2 border-border pl-2 text-foreground">
                      {value.text}
                    </blockquote>
                  </li>)}
                </ul>
              </li>;
            })}
          </ul>
        </details>
      )}
      {data.domain_values.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer">查看跨章关联记录</summary>
          <ul className="mt-2 space-y-3">
            {data.domain_values.map((item) => (
              <li key={item.target} className="border-t border-border pt-2">
                <p className="break-words">{assertionLabels[item.continuity_values[0]?.kind] ?? "关联记录"}
                  {" · "}{domainStateLabels[item.state] ?? item.state}</p>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <div><p className="font-medium text-foreground">章节标注</p>
                    {item.formal_values.map((value, index) => <pre key={index} className="mt-1 whitespace-pre-wrap break-words">
                      {assertionText(value)}
                    </pre>)}
                  </div>
                  <div><p className="font-medium text-foreground">跨章关联判断</p>
                    {item.continuity_values.map((value, index) => <pre key={index} className="mt-1 whitespace-pre-wrap break-words">
                      {assertionText(value)}
                    </pre>)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
      {data.evidence.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer">查看原文证据区间</summary>
          <ul className="mt-2 space-y-2">
            {data.evidence.map((item) => (
              <li key={item.evidence_id}>
                <span>第 {item.chapter_id} 章 · 段落 {item.paragraph_id} · 字符 [{item.char_start}, {item.char_end})</span>
                <blockquote className="mt-1 border-l-2 border-border pl-2 text-foreground">{item.text}</blockquote>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
