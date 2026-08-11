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

// 分块曲线

export interface ChunkCurvePoint {
  chunk_id: number;
  pos_density: number | null;
  neg_density: number | null;
  net_density: number | null;
  smoothed_density: number | null;
  tension_proxy: number | null;
  tension_composite?: number | null;
  surface_tension?: number | null;
}

export interface ChunkCharacter {
  name: string;
  role_function?: string | null;
  action?: string | null;
  emotion_score?: string | null;
}

export interface ChunkRelation {
  from_char: string;
  to_char: string;
  type: string;
  change: string;
}

export interface ChunkDialogue {
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

export interface ChunkAnnotation {
  chunk_id: number;
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
  characters: ChunkCharacter[];
  relations: ChunkRelation[];
  dialogues: ChunkDialogue[];
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
  rerun_required?: boolean;
  rerun_reason?: string | null;
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
  first_chunk_id: number;
  last_chunk_id: number;
  anchor_chunk_ids: number[];
  setup_summary: string;
  setup_kind: ForeshadowingSetupKind | string;
  expected_payoff_family: string;
  payoff_likelihood: ForeshadowingPayoffLikelihood;
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
  first_seen_chunk: number;
  last_seen_chunk: number;
  state_revision: number;
  state: Record<string, unknown>;
}

export interface GraphEdge {
  relation_id: string;
  relation_version_id: number;
  relation_revision: number;
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

export interface GraphTextEvidence {
  reason: string;
  chunk_id: number;
}

export interface GraphFactEvidence {
  fact_id: string;
  fact_revision: number;
  reason: string;
}

export type GraphEvidence = GraphTextEvidence | GraphFactEvidence;

export interface GraphChange {
  change_id: string;
  change_kind: "state" | "relation";
  graph_version_id: string;
  chapter_id: number;
  chapter_order: number;
  fact_id: string;
  fact_revision: number;
  effective_chunk_id: number;
  changes: Array<Record<string, unknown>>;
  evidence: GraphEvidence[];
  entity_id?: number | null;
  entity_name?: string | null;
  relation_id?: string | null;
  relation_version_id?: number | null;
  relation_revision?: number | null;
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
  graph_version_id: string;
  chapter_id: number;
  chapter_order: number;
  first_chunk_id: number;
  last_chunk_id: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphChangesPageResponse {
  changes: GraphChange[];
  page_info: GraphChangesPageInfo;
}

// 时间轴

// 更新 Timeline 类型定义，与后端 API 响应结构对齐

export interface TimelineMeta {
  novel_id: string;
  novel_name: string;
  total_chunks: number;
}

export interface TimelinePhase {
  name: "引入期" | "发展期" | "高潮期" | "收束期";
  start: number;
  end: number;
  ratio: number;
}

export interface PlotFlags {
  is_pivot: boolean;
  is_cliffhanger: boolean;
  tension_percentile: number;
}

export interface TimelineGraphChange {
  change_id: string;
  change_kind: "state" | "relation";
  graph_version_id: string;
  chapter_id: number;
  fact_id: string;
  fact_revision: number;
  effective_chunk_id: number;
  changes: Array<Record<string, unknown>>;
  evidence: GraphEvidence[];
  entity_id?: number | null;
  entity_name?: string | null;
  relation_id?: string | null;
  relation_version_id?: number | null;
  relation_revision?: number | null;
  from_char?: string | null;
  to_char?: string | null;
  relation_type?: string | null;
  relation_change_kind?: string | null;
  directionality?: "directed" | "bidirectional" | null;
}

export interface LifecycleTimelineEvent {
  entity_id: number;
  character_name: string;
  lifecycle_type: "entry" | "exit";
}

export interface TimelineNode {
  node_id: string;
  anchor_chunk_id: number;
  progress: number;
  importance_score: number;
  level: 1 | 2 | 3;
  summary: string;
  characters: string[];
  phase_name: "引入期" | "发展期" | "高潮期" | "收束期";
  node_type: "plot" | "state" | "relation" | "lifecycle";
  node_subtype: "plot" | "state" | "entry" | "exit" | "assert" | "reinforce" | "weaken" | "break" | "refine" | "supersede" | "retract";
  score_breakdown: Record<string, number>;
  plot_flags?: PlotFlags | null;
  graph_changes?: TimelineGraphChange[] | null;
  lifecycle_events?: LifecycleTimelineEvent[] | null;
}

export interface TimelineCompositeNode {
  node_id: string;
  anchor_chunk_id: number;
  start_chunk_id: number;
  end_chunk_id: number;
  progress: number;
  start_progress: number;
  end_progress: number;
  importance_score: number;
  level: 1 | 2 | 3;
  summary: string;
  characters: string[];
  phase_name: "引入期" | "发展期" | "高潮期" | "收束期";
  node_type: "plot" | "state" | "relation" | "lifecycle";
  node_subtypes: ("plot" | "state" | "entry" | "exit" | "assert" | "reinforce" | "weaken" | "break" | "refine" | "supersede" | "retract")[];
  representative_node_id: string;
  child_node_ids: string[];
}

export interface TimelineResponse {
  meta: TimelineMeta;
  phases: TimelinePhase[];
  composite_nodes: TimelineCompositeNode[];
  atomic_nodes: TimelineNode[];
  tension_curve?: number[];
}

// 指标

export interface NarrativeStructureMetrics {
  act1_ratio?: number;
  act2_ratio?: number;
  act3_ratio?: number;
  climax_spacing?: number;
  middle_collapse_index?: number;
  event_density?: Record<string, number>;
  cliffhanger_rate?: number;
  climax_count?: number;
  climax_positions?: number[];
  climax_heights?: number[];
  peak_escalation?: string;
  dominant_climax_pos?: number;
}

export interface EmotionStatsMetrics {
  pos_neg_ratio?: number;
  positive_ratio?: number;
  negative_ratio?: number;
  neutral_ratio?: number;
  recovery_speed?: number;
  pivot_moment_density?: number;
  lexical_emotion_trend?: string;
}

export interface CharacterStatsMetrics {
  network_density?: number | null;
  greimas_coverage?: number | null;
  function_coverage_distribution?: Record<string, number> | null;
  antagonist_strength_gap?: number | null;
  relation_change_freq?: number | null;
  degree_centrality?: Record<string, number> | null;
}

export interface StyleStatsMetrics {
  vocab_breadth: number;
  avg_sent_len: number;
  dialogue_ratio: number;
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
