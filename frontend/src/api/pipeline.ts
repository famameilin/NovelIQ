import { apiClient } from "./client";

export interface PipelineAssertion {
  kind: string;
  payload: Record<string, unknown>;
  outcome: string;
  evidence_ids: string[];
}

export interface PipelineSnapshot {
  cutoff_hash: string;
  round_kind: string;
  round_number: number;
  released_at: string;
  formal_count: number;
  case_states: Record<"pending" | "resolved" | "deferred" | "contested", number>;
  formal_policy: string;
  pending_dependency_count: number;
  contested_partition_count: number;
  evidence: Array<{
    evidence_id: string;
    chapter_id: number;
    paragraph_id: number;
    char_start: number;
    char_end: number;
    text_hash: string;
    text: string;
  }>;
  cases: Array<{
    case_id: string;
    state: "pending" | "resolved" | "deferred" | "contested";
    description: string;
    type: string;
    target_ref: Record<string, unknown>;
    source_evidence: string[];
    continuity_claims: PipelineAssertion[];
  }>;
  domain_values: Array<{
    target: string;
    state: string;
    projection_hash: string;
    formal_values: PipelineAssertion[];
    continuity_values: PipelineAssertion[];
  }>;
}

export async function getPipelineSnapshot(novelId: string, taskId: string): Promise<PipelineSnapshot> {
  const { data } = await apiClient.get<PipelineSnapshot>(`/api/novels/${novelId}/pipeline`, {
    params: { task_id: taskId },
  });
  return data;
}
