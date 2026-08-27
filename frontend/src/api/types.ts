// 小说

export interface Novel {
  novel_id: string;
  title: string;
  filename: string;
  author?: string;
  upload_time: string | null;
  file_size: number;
}

export interface NovelUploadResponse {
  novel_id: string;
  title: string;
  message: string;
}

// 分析任务

export type TaskStatus =
  | "pending"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";

export interface TaskStatusResponse {
  novel_id: string;
  task_id: string;
  status: TaskStatus;
  progress: number;
  current_step: string;
  error?: string;
  stage?: string;
  sub_stage?: string;
  current?: number;
  total?: number;
  message?: string;
  llm_outputs?: string[];
}

export interface AnalysisTask {
  task_id: string;
  novel_id: string;
  status: TaskStatus;
  created_at: string | null;
  completed_at?: string;
  error?: string;
}

export interface AnalysisStartResponse {
  novel_id: string;
  task_id: string;
  message: string;
}

export interface BatchDeleteTaskFailure {
  task_id: string;
  reason: string;
}

export interface BatchDeleteTasksResponse {
  success: boolean;
  message: string;
  deleted_count: number;
  failed_count: number;
  deleted_ids: string[];
  failed_ids: BatchDeleteTaskFailure[];
}

// 角色

export interface Character {
  name: string;
  appearance_count: number;
  dominant_role_function: string;
  role_function_distribution?: Record<string, number>;
  dominant_role_ratio?: number;
  narrative_focus_score?: number | null;
  is_focus_character?: boolean;
  avg_emotion_score?: number | null;
}

// 段落曲线（M4：从分块粒度迁移到段落粒度，x 坐标统一使用 0-1 position 值域）

export interface ParagraphCurvePoint {
  paragraph_id: number;
  chapter_id: number;
  paragraph_index: number;
  global_start_char: number;
  global_end_char: number;
  position: number; // 0-1 数字坐标
  char_count: number;
  token_count: number;
  pos_density: number | null;
  neg_density: number | null;
  net_density: number | null;
  smoothed_net_density: number | null;
  surface_tension: number | null;
  smoothed_surface_tension: number | null;
}

// 情绪趋势窗口（展示层缩放自适应窗口聚合，覆盖率为窗内命中段占比）
export interface EmotionTrendWindow {
  window_index: number;
  position: number;
  start_position: number;
  end_position: number;
  paragraph_start: number;
  paragraph_end: number;
  chapter_start: number;
  chapter_end: number;
  pos_coverage: number;
  neg_coverage: number;
  pooled_pos_density: number | null;
  pooled_neg_density: number | null;
  pooled_net_density: number | null;
  smoothed_pos_coverage: number | null;
  smoothed_neg_coverage: number | null;
  smoothed_pooled_pos_density: number | null;
  smoothed_pooled_neg_density: number | null;
  smoothed_pooled_net_density: number | null;
  token_total: number;
  hit_paragraphs: number;
  paragraph_total: number;
}

// 章节指标汇总（M4）

export interface ChapterMetricSummary {
  chapter_id: number;
  paragraph_count: number;
  total_chars: number;
  total_tokens: number;
  pos_density: number | null;
  neg_density: number | null;
  net_density: number | null;
  fight_density: number | null;
  exclaim_per_100_chars: number | null;
  question_per_100_chars: number | null;
  pause_per_100_chars: number | null;
  dialogue_ratio: number | null;
  avg_sent_len: number | null;
  sent_len_std: number | null;
  ttr: number | null;
  mtld: number | null;
  narrative_function: string | null;
  pivot_moment: boolean | null;
  cliffhanger: boolean | null;
  emotional_valence: string | null;
}

export interface BookAggregateStats {
  total_chapters: number;
  total_paragraphs: number;
  total_chars: number;
  total_tokens: number;
  pos_density: number | null;
  neg_density: number | null;
  net_density: number | null;
  fight_density: number | null;
  exclaim_per_100_chars: number | null;
  question_per_100_chars: number | null;
  pause_per_100_chars: number | null;
  dialogue_ratio: number | null;
  avg_sent_len: number | null;
  sent_len_std: number | null;
  ttr: number | null;
  mtld: number | null;
  chapter_narrative_function_share: Record<string, number>;
  chapter_pivot_rate: number | null;
  chapter_cliffhanger_rate: number | null;
  chapter_emotional_valence_share: Record<string, number>;
}

export interface ChapterMetricsResponse {
  chapters: ChapterMetricSummary[];
  book: BookAggregateStats;
}

export interface GlobalStats {
  total_chapters?: number | null;
  total_chars?: number | null;
  avg_mtld?: number | null;
  avg_ttr?: number | null;
  avg_sent_len?: number | null;
  emotion_std?: number | null;
  emotion_max?: number | null;
  emotion_min?: number | null;
  rhythm_avg?: number | null;
  rhythm_std?: number | null;
  rhythm_max?: number | null;
  rhythm_min?: number | null;
}

export interface ChapterCharacter {
  name: string;
  role_function?: string | null;
  action?: string | null;
  emotion_score?: string | null;
}

export interface ChapterRelation {
  from_char: string;
  to_char: string;
  type: string;
  change: string;
}

export interface ChapterDialogue {
  speaker: string[];
  length?: number | null;
}

export type ForeshadowingSetupKind =
  | "异常物件"
  | "异常规则"
  | "隐藏身份"
  | "明确承诺"
  | "明确威胁"
  | "倒计时"
  | "未解释能力"
  | "因果引线"
  | "其他";

export type ForeshadowingPayoffLikelihood = "high" | "medium" | "low";
export type DiagnosisGenreLabel = "科幻" | "悬疑" | "历史" | "仙侠" | "玄幻" | "都市" | "通用";
export type DiagnosisStyleLabel =
  | "硬核"
  | "史诗"
  | "哲思"
  | "严肃"
  | "黑暗"
  | "慢热"
  | "高概念"
  | "实验性"
  | "热血"
  | "轻松"
  | "寓言性"
  | "冷峻"
  | "权谋"
  | "爽文";

export interface ChapterAnnotation {
  chapter_id: number;
  emotional_valence?: string | null;
  event_type?: string | null;
  pivot_moment?: boolean | null;
  cliffhanger?: boolean | null;
  has_foreshadowing?: boolean | null;
  is_strong_setup?: boolean | null;
  foreshadowing_type?: string | null;
  setup_kind?: ForeshadowingSetupKind | null;
  foreshadowing_desc?: string | null;
  setup_summary?: string | null;
  why_unresolved_now?: string | null;
  expected_payoff_family?: string | null;
  payoff_likelihood?: ForeshadowingPayoffLikelihood | null;
  linked_setup_id?: string | null;
  characters: ChapterCharacter[];
  relations: ChapterRelation[];
  dialogues: ChapterDialogue[];
}

// 主题

// LDA 主题建模结果类型定义。label 字段为可选预留字段，
//       后端当前不返回，供未来 LLM 诊断阶段生成主题命名时使用

export interface Topic {
  topic_id: number;
  words: string[];
  weight: number;
  // 可选字段：后端暂未返回，预留供 LLM 诊断阶段生成主题命名时使用
  label?: string;
}

// 诊断

export interface DiagnosisResult {
  genre_labels?: DiagnosisGenreLabel[] | null;
  style_labels?: DiagnosisStyleLabel[] | null;
  foreshadow_expectation?: number | null;
  narrative_arc_type?: string | null;
  arc_scores?: Record<string, number> | null;
  diagnosis?: string | null;
  value_logic_type?: string | null;
  value_logic_reason?: string | null;
  power_stance_score?: number | null;
  power_stance_reason?: string | null;
  common_people_dignity?: number | null;
  dignity_reason?: string | null;
  cultural_depth_score?: number | null;
  cultural_depth_reason?: string | null;
  focus_structure?: "single" | "dual" | "ensemble" | null;
  focus_characters?: string[] | null;
  topic_labels?: string[] | null;
  core_cast?: string[] | null;
  main_characters?: string[] | null;
  theme_color?: string | null;
}

export interface ForeshadowingThread {
  setup_id: string;
  first_chapter_id: number;
  last_chapter_id: number;
  anchor_chapter_ids: number[];
  setup_summary: string;
  setup_kind: ForeshadowingSetupKind | string;
  expected_payoff_family: string;
  payoff_likelihood: ForeshadowingPayoffLikelihood;
  confidence: string | null;
  strength: "high" | "medium" | string;
  status: "open" | "reinforced" | "likely_paid_off" | "archived" | string;
  active: boolean;
  latest_reason?: string | null;
  latest_why_unresolved_now?: string | null;
}

// 知识图谱

export interface GraphNode {
  entity_id: number;
  name: string;
  entity_type: "character" | "location" | "item" | "organization";
  tags?: string[] | null;
  aliases?: string[] | null;
  // 2026-08-13 P2-5: 后端可能下发 null（生命周期数据缺失），放宽为可空
  first_seen_chapter: number | null;
  last_seen_chapter: number | null;
  state_chapter_id: number | null;
  state: Record<string, unknown>;
}

export interface GraphEdge {
  relation_id: string;
  state_chapter_id: number;
  source_entity_id: number;
  target_entity_id: number;
  source_name: string;
  target_name: string;
  relation_type: string;
  directionality: "directed" | "bidirectional";
  relation_semantics: "ordinary" | "same_character";
  attributes: Record<string, unknown>;
  is_active: boolean;
  changes: Array<Record<string, unknown>>;
}

export interface GraphChange {
  change_id: string;
  change_kind: "state" | "relation";
  chapter_id: number;
  chapter_order: number;
  fact_id: string;
  effective_chapter_id: number;
  changes: Array<Record<string, unknown>>;
  entity_id?: number | null;
  entity_name?: string | null;
  relation_id?: string | null;
  from_entity_id?: number | null;
  to_entity_id?: number | null;
  from_name?: string | null;
  to_name?: string | null;
  relation_type?: string | null;
  relation_change_kind?: string | null;
  directionality?: "directed" | "bidirectional" | null;
  relation_semantics?: "ordinary" | "same_character" | null;
}

export interface GraphChangesPageInfo {
  limit: number;
  returned_count: number;
  total: number;
  has_more: boolean;
  next_cursor?: string | null;
}

export interface GraphData {
  chapter_id: number;
  chapter_order: number;
  first_chapter_id: number;
  last_chapter_id: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphChangesPageResponse {
  changes: GraphChange[];
  page_info: GraphChangesPageInfo;
}

// 时间轴 — 2026-08-20 事件森林一树一节点新合同

export interface TimelineMeta {
  novel_id: string;
  novel_name: string;
  total_chapters: number;
}

export interface TimelinePhase {
  name: "引入期" | "发展期" | "高潮期" | "收束期";
  start: number;
  end: number;
  ratio: number;
}

// ── 事件森林新合同（一树一节点）与后端 src/api/models/event_timeline.py 严格对齐 ──

export interface TimelineEventParticipant {
  name: string;
  role: string;
  entity_id?: number | null;
  entity_type?: string | null;
  // 透传保留未知字段
  [key: string]: unknown;
}

export interface TimelineEventSecondaryGroup {
  target_event_id: string;
  branch: string[];
}

export interface TimelineEventNode {
  tree_id: string;
  root_event_id: string;
  title?: string | null;
  summary: string;
  anchor_chapter_id: number;
  anchor_chapter_order: number;
  start_chapter_id: number;
  end_chapter_id: number;
  start_progress: number;
  end_progress: number;
  progress: number;
  chapter_ids: number[];
  char_start: number;
  char_end: number;
  participants: TimelineEventParticipant[];
  character_names: string[];
  importance_score: number;
  level: 1 | 2 | 3;
  phase_name: "引入期" | "发展期" | "高潮期" | "收束期";
  main_chain: string[];
  secondary_groups: TimelineEventSecondaryGroup[];
  causal_in: number;
  causal_out: number;
  node_type: "event";
}

export interface TimelineEventCausalEdge {
  edge_id: string;
  edge_type: "causal";
  source_event_id: string;
  target_event_id: string;
  source_chapter_id: number;
  target_chapter_id: number;
  is_active: boolean;
  evidence: Array<Record<string, unknown>>;
  expired_at?: string | null;
}

export interface TimelineEventForeshadowingEdge {
  setup_id: string;
  setup_event_id: string;
  payoff_event_id?: string | null;
  first_chapter_id: number;
  last_chapter_id: number;
  setup_summary: string;
  status: string;
  active: boolean;
}

export interface EventTimelineResponse {
  meta: TimelineMeta;
  phases: TimelinePhase[];
  nodes: TimelineEventNode[];
  causal_edges: TimelineEventCausalEdge[];
  foreshadowing_edges: TimelineEventForeshadowingEdge[];
  derived_event_order: string[];
  tension_curve?: number[] | null;
  phase_basis: "tension" | "fixed_percentage";
  total_chapters: number;
}

// 指标

export interface NarrativeStructureMetrics {
  act1_ratio?: number | null;
  act2_ratio?: number | null;
  act3_ratio?: number | null;
  /** 相邻高潮归一化进度差均值 [0,1] */
  climax_spacing?: number | null;
  middle_collapse_index?: number | null;
  chapter_narrative_function_share?: Record<string, number> | null;
  cliffhanger_rate?: number | null;
  climax_count?: number | null;
  climax_positions?: number[] | null;
  climax_heights?: number[] | null;
  peak_escalation?: string | null;
  dominant_climax_pos?: number | null;
}

export interface EmotionStatsMetrics {
  lexical_pos_neg_ratio?: number | null;
  arc_delta?: number | null;
  positive_ratio?: number | null;
  negative_ratio?: number | null;
  neutral_ratio?: number | null;
  /** 情绪恢复的归一化进度距离 [0,1] */
  recovery_speed?: number | null;
  chapter_pivot_rate?: number | null;
  lexical_emotion_trend?: string | null;
}

export interface CharacterStatsMetrics {
  network_density?: number | null;
  greimas_coverage?: number | null;
  function_coverage_distribution?: Record<string, number> | null;
  antagonist_strength_gap?: number | null;
  relation_change_per_10k_chars?: number | null;
  degree_centrality?: Record<string, number> | null;
}

export interface StyleStatsMetrics {
  string_token_diversity?: number | null;
  avg_word_len?: number | null;
  avg_sent_len?: number | null;
  dialogue_ratio?: number | null;
  sent_len_std?: number | null;
  tone_distribution?: Record<string, number> | null;
  function_word_vector?: Record<string, number> | null;
}

// 通用

export interface ApiError {
  detail: string;
}

// 分页

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface BatchDeleteRequest {
  novel_ids: string[];
}

export interface BatchDeleteResponse {
  deleted: string[];
  failed: string[];
}
