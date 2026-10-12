/** 两页分别消费独立业务投影，节点身份和变化身份不能互换 */
export type ProgressionDimension = "plot" | "character" | "relationship" | "foreshadowing";
export interface NarrativeChapter { chapter_id: number; order: number; title: string }
export interface ProgressionChange {
  progression_change_id: string;
  dimension: ProgressionDimension;
  subject_id: string;
  subject_title: string;
  title: string;
  chapter_id: number;
  chapter_order: number;
  before: unknown;
  after: unknown;
  deltas: Array<{ field: string; before: unknown; after: unknown }>;
  action: string | null;
  evidence_scope: "chapter" | "paragraph";
  anchor_paragraph_ids: number[];
  evidence: Array<Record<string, unknown>>;
  source_event_ids: string[];
  source_fact_ids: string[];
}
export interface ProgressionTimelineResponse {
  run_id: string;
  chapters: NarrativeChapter[];
  through_chapter_id: number | null;
  changes: ProgressionChange[];
  states: Array<{ subject_id: string; subject_title: string; dimension: ProgressionDimension; state: unknown; chapter_id: number; chapter_order: number }>;
  subjects: Array<{ subject_id: string; subject_title: string; dimension: ProgressionDimension }>;
  total: number;
  next_cursor: string | null;
  distribution: Array<{ chapter_id: number; chapter_order: number; dimension: ProgressionDimension; count: number }>;
}
export interface NarrativeTreeNode {
  node_id: string;
  kind: "root" | "arc" | "group" | "event" | "unassigned";
  title: string;
  parent_id: string | null;
  arc_id?: string | null;
  tree_id?: string | null;
  event_id?: string | null;
  child_count: number;
  chapter_id?: number | null;
  chapter_order?: number | null;
  is_foreshadowing_root?: boolean;
  foreshadowing_status?: "open" | "reinforced" | "likely_paid_off" | null;
}
export interface NarrativeTreeResponse {
  run_id: string;
  title: string;
  chapters: NarrativeChapter[];
  total_events: number;
  arcs: Array<{ arc_id: string; parent_arc_id: string | null; kind: "main" | "subplot"; title: string; objective: string; role: string; reason: string; evidence: Array<Record<string, unknown>> }>;
  nodes: NarrativeTreeNode[];
  edges: Array<{ source_id: string; target_id: string; kind: string }>;
  total: number;
  next_cursor: string | null;
  matches: Array<{ node_id: string; title: string; ancestor_ids: string[]; chapter_id: number | null; chapter_order: number | null }>;
}
export interface NarrativeTreeDetail extends Omit<NarrativeTreeNode, "child_count"> {
  path: NarrativeTreeNode[];
  role: string | null;
  reason: string | null;
  evidence: Array<Record<string, unknown>>;
  evidence_scope: "chapter" | "paragraph";
  anchor_paragraph_ids: number[];
  participants: Array<Record<string, unknown>>;
  relations: Array<{ source_id: string; target_id: string; kind: string; title: string; direction: "incoming" | "outgoing"; related_node: NarrativeTreeNode; ancestor_ids: string[] }>;
  references: Array<{ arc_id: string; event_id: string; arc_title: string; event_title: string; role: string; reason: string; evidence: Array<Record<string, unknown>> }>;
}
export interface NarrativeSource {
  chapter_id: number;
  title: string;
  paragraphs: Array<{ paragraph_id: number; paragraph_index: number; text: string }>;
}
