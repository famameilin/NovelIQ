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
export interface PlotlineTimelineResponse {
  run_id: string;
  organization_status?: "ready" | "pending_diagnosis";
  chapters: NarrativeChapter[];
  through_chapter_id: number | null;
  changes: PlotlineChange[];
  states: Array<{ subject_id: string; subject_title: string; dimension: PlotlineDimension; state: unknown; chapter_id: number; chapter_order: number }>;
  subjects: Array<{ subject_id: string; subject_title: string; dimension: PlotlineDimension }>;
  total: number;
  next_cursor: string | null;
  distribution: Array<{ chapter_id: number; chapter_order: number; dimension: PlotlineDimension; count: number }>;
}

/* ===== 事件声明与统一正式身份契约 =====
 * 列表仅 events（顶层大事件）分页，其余字段每页完整；
 * 子事件不经列表下发，通过事件详情卡的 direct_children 逐级访问 */
export const EVENT_TREE_CONTRACT_VERSION = "event-tree-declarations-v1";
export interface EventTreeChapter { chapter_id: number; title: string; chapter_order: number }
export interface EventTreeCounts {
  top_level_events: number;
  child_events: number;
  all_events: number;
  declarations: number;
  outcomes: number;
  event_outcome_links: number;
  arcs: number;
  event_arc_links: number;
  relations: number;
  foreshadowing_actions: number;
}
export interface EventTreeArc { arc_id: string; parent_arc_id: string | null; kind: string; title: string; objective: string }
export interface EventTreeEvent {
  event_id: string;
  title: string;
  summary: string;
  event_type: string;
  status: string;
  first_text_position: number;
  chapter_id: number;
  chapter_order: number;
}
export interface EventTreeOutcome { outcome_id: string; title: string; description: string; first_text_position: number }
export interface EventArcLinkItem { event_id: string; arc_id: string; role: string; reason: string }
export interface EventOutcomeLinkItem { event_id: string; outcome_id: string; reason: string }
export interface EventRelationItem {
  relation_id?: string;
  source_kind: "event";
  source_id: string;
  target_kind: "event";
  target_id: string;
  relation_type: string;
  reason: string;
  evidence?: Array<Record<string, unknown>>;
  locator?: { target_kind: "event"; target_id: string; top_level_event_id: string | null; ancestor_event_ids: string[]; evidence_position: number | null; title: string };
  top_level_event_id?: string | null;
  ancestor_event_ids?: string[];
  evidence_position?: number | null;
}
export interface ForeshadowingActionItem {
  action_id: string;
  action_type: "setup" | "reinforce" | "payoff";
  endpoint_kind: "event";
  root_event_id: string;
  target_event_id: string | null;
  chapter_id: number;
  chapter_order: number;
}
export interface EventTreeListResponse {
  run_id: string;
  contract_version: typeof EVENT_TREE_CONTRACT_VERSION;
  organization_status?: "ready" | "pending_diagnosis";
  chapters: EventTreeChapter[];
  counts: EventTreeCounts;
  arcs: EventTreeArc[];
  events: EventTreeEvent[];
  outcomes: EventTreeOutcome[];
  event_arc_links: EventArcLinkItem[];
  event_outcome_links: EventOutcomeLinkItem[];
  relations: EventRelationItem[];
  foreshadowing_actions: ForeshadowingActionItem[];
  next_cursor: string | null;
}
export interface EventCardDetail {
  kind: "event";
  event_id: string;
  run_id: string;
  title: string;
  summary: string;
  progress: string | null;
  event_type: string;
  status: string;
  arcs: Array<{ arc_id: string; title: string; kind: string; role: string; reason: string }>;
  characters: Array<Record<string, unknown>>;
  direct_children: Array<{ event_id: string; title: string; event_type: string; status: string }>;
  evidence: Array<Record<string, unknown>>;
  source_chapters: number[];
  evidence_scope: "chapter" | "paragraph";
  ancestry: string[];
  revision_id: string;
  relations: EventRelationItem[];
}
export interface NarrativeSource {
  locator?: EventRelationItem["locator"] | {
    target_kind: "declaration";
    target_id: string;
    top_level_event_id: null;
    ancestor_event_ids: [];
    evidence_position: number | null;
    title: string;
  };
  evidence?: Array<Record<string, unknown>>;
  evidence_scope?: "chapter" | "paragraph";
  chapter_id: number;
  title: string;
  paragraphs: Array<{ paragraph_id: number; paragraph_index: number; text: string }>;
}
