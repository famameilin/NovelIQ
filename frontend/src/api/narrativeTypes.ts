/** 两页分别消费独立业务投影，节点身份和变化身份不能互换 */
export type PlotlineDimension = "plot" | "character" | "relationship" | "foreshadowing";
export interface NarrativeChapter { chapter_id: number; order: number; title: string }
export interface PlotlineChange {
  plotline_change_id: string;
  dimension: PlotlineDimension;
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
export interface PlotlineState {
  subject_id: string;
  subject_title: string;
  dimension: PlotlineDimension;
  state: unknown;
  chapter_id: number;
  chapter_order: number;
}
export interface PlotlineTimelineResponse {
  run_id: string;
  organization_status?: "ready" | "pending_diagnosis";
  chapters: NarrativeChapter[];
  through_chapter_id: number | null;
  changes: PlotlineChange[];
  states: PlotlineState[];
  state_counts: Partial<Record<PlotlineDimension, number>>;
  state_total: number;
  total: number;
  next_cursor: string | null;
  distribution: Array<{ chapter_id: number; chapter_order: number; dimension: PlotlineDimension; count: number }>;
}
export interface PlotlineStatesResponse {
  states: PlotlineState[];
  state_counts?: Partial<Record<PlotlineDimension, number>>;
  state_total?: number;
  total: number;
  next_cursor: string | null;
}
export interface PlotlineSubjectsResponse {
  subjects: Array<{ subject_id: string; subject_title: string; dimension: PlotlineDimension }>;
  total: number;
  next_cursor: string | null;
}

/** 全书事件树结构与真实事件一次返回，事件线入口引用独立树身份 */
export interface EventTreeChapter { chapter_id: number; title: string; chapter_order: number }
export interface EventTreeCounts {
  event_lines: number;
  trees: number;
  tree_references: number;
  all_events: number;
  outcomes: number;
  relations: number;
  foreshadowing_actions: number;
}
export interface EventQueueItem {
  tree_id: string;
  title: string;
  description: string;
  is_event_line: boolean;
  line_name?: string | null;
  event_ids: string[];
}
export interface QueueReferenceItem { parent_tree_id: string; child_tree_id: string; reason: string; evidence: Array<Record<string, unknown>> }
export interface EventTreeEvent {
  from: number;
  to: number;
  event_id: string;
  is_event_line: boolean;
  title: string;
  problem: string;
  summary: string;
  event_type: string;
  status: string;
  first_text_position: number;
  chapter_id: number;
  chapter_order: number;
}
export interface EventTreeOutcome { outcome_id: string; title: string; description: string; first_text_position: number }
export interface EventRelationItem {
  relation_id?: string;
  source_kind: "event";
  source_id: string;
  target_kind: "event";
  target_id: string;
  relation_type: string;
  reason: string;
  evidence?: Array<Record<string, unknown>>;
  locator?: { target_kind: "event"; target_id: string; tree_id: string; tree_position: number; event_line_ids: string[]; evidence_position: number | null; title: string };
  tree_id?: string;
  tree_position?: number;
  event_line_ids?: string[];
  evidence_position?: number | null;
}
export interface ForeshadowingActionItem {
  action_id: string;
  action_type: "setup" | "reinforce" | "payoff";
  endpoint_kind: "event";
  source_event_id: string;
  target_event_id: string | null;
  chapter_id: number;
  chapter_order: number;
}
export interface EventTreeListResponse {
  run_id: string;
  organization_status?: "ready" | "pending_diagnosis";
  chapters: EventTreeChapter[];
  counts: EventTreeCounts;
  event_line_ids: string[];
  queues: EventQueueItem[];
  events: EventTreeEvent[];
  queue_references: QueueReferenceItem[];
  outcomes: EventTreeOutcome[];
  relations: EventRelationItem[];
  foreshadowing_actions: ForeshadowingActionItem[];
  next_cursor: null;
}
export interface EventCardDetail {
  from: number;
  to: number;
  kind: "event";
  event_id: string;
  is_event_line: boolean;
  run_id: string;
  title: string;
  summary: string;
  progress: string | null;
  event_type: string;
  status: string;
  characters: Array<Record<string, unknown>>;
  direct_children: Array<{ event_id: string; title: string; event_type: string; status: string }>;
  evidence: Array<Record<string, unknown>>;
  source_chapters: number[];
  evidence_scope: "chapter" | "paragraph";
  tree_id: string;
  tree_position: number;
  event_line_ids: string[];
  direct_parents: EventCardDetail["direct_children"];
  relations: EventRelationItem[];
}
export interface NarrativeSource {
  locator?: EventRelationItem["locator"];
  evidence?: Array<Record<string, unknown>>;
  evidence_scope?: "chapter" | "paragraph";
  chapter_id: number;
  title: string;
  paragraphs: Array<{ paragraph_id: number; paragraph_index: number; text: string }>;
}

export interface ChapterEventDetail {
  from: number;
  to: number;
  run_id: string;
  chapter_id: number;
  event_id: string;
  title: string;
  problem: string;
  summary: string;
  status: string;
  progress: string | null;
  event_type: string;
  participants: Array<{ entity: { entity_id?: string | null; name: string; entity_type: string }; role: string; [key: string]: unknown }>;
  evidence: EventCardDetail["evidence"];
}
