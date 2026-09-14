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
  emotional_valence: number | null;
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
  chapter_emotional_valence_share: Record<string, number>; // 键为分值 -2..2 的字符串形式
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
  emotional_valence?: number | null;
  event_type?: string | null;
  pivot_moment?: boolean | null;
  cliffhanger?: boolean | null;
  has_foreshadowing?: boolean | null;
  is_strong_setup?: boolean | null;
  foreshadowing_desc?: string | null;
  why_unresolved_now?: string | null;
  payoff_likelihood?: ForeshadowingPayoffLikelihood | string | null;
  // 2026-09-13 伏笔入森林：非埋设章挂树时指向伏笔树根（埋设事件 id）
  foreshadowing_root_event_id?: string | null;
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

// 2026-09-13 伏笔即事件树：伏笔树 = isforeshadowing 根事件 + foreshadowing 挂树边
export interface ForeshadowingTree {
  root_event_id: string;
  tree_id: string;
  first_chapter_id: number;
  last_chapter_id: number;
  anchor_chapter_ids: number[];
  description: string;
  payoff_likelihood: ForeshadowingPayoffLikelihood | string | null;
  strength: "high" | "medium" | string | null;
  status: "open" | "reinforced" | "likely_paid_off" | string;
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
  name?: string;
  role: string;
  entity_id?: number | null;
  entity_type?: string | null;
  entity?: {
    name: string;
    entity_id?: number | null;
    entity_type?: string | null;
  } | null;
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
  root_event_id: string;
  tree_id: string;
  payoff_event_id?: string | null;
  first_chapter_id: number;
  last_chapter_id: number;
  description: string;
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

// Tab 级聚合（前端每 tab 一个 API；响应只含复合数据与展示主体，
// 与后端 src/api/models/tabs.py 严格对齐）

export interface TopicModelMetaInfo {
  model_key: string;
  library_version: string;
  pipeline_version: string;
  num_topics: number;
  artifact_key: string;
}

export interface TopicDistributionEntry {
  topic_id: number;
  weight: number;
}

export interface ChapterTopicDistribution {
  chapter_id: number;
  chapter_sequence: number;
  chapter_title: string;
  token_total: number | null;
  distribution: TopicDistributionEntry[] | null;
}

export interface KeywordScoreItem {
  word: string;
  score: number;
}

/** 主题总览 tab：主题词 + 全书/章节完整分布 + TextRank 关键词 + 诊断主题标签 */
export interface TopicsOverviewTabResponse {
  run_id: string;
  model: TopicModelMetaInfo | null;
  topics: Topic[];
  distribution: TopicDistributionEntry[] | null;
  chapters: ChapterTopicDistribution[];
  keywords: KeywordScoreItem[];
  /** 诊断切片：LLM 主题命名，按 topic_id 顺序对齐 topics */
  topic_labels: string[] | null;
  unavailable_reason: string | null;
  keyword_unavailable_reason: string | null;
}

/** 实体与短语 tab：仅聚合统计，不含实体候选 span 明细 */
export interface EntitySurfaceCount {
  surface_text: string;
  entity_type: string;
  count: number;
}

export interface LinguisticEntitiesTabResponse {
  run_id: string;
  count_by_type: Record<string, number>;
  surface_top: EntitySurfaceCount[];
  total_char_count: number;
  metric_hit_count: number;
  fixed_phrase_density: number | null;
  four_char_candidate_count: number;
  total_hits: number;
  unavailable_reason: string | null;
}

/** 仪表盘 tab：原 8 个并发请求合并为一次拉取 */
export interface DashboardTabResponse {
  run_id: string;
  narrative_structure: NarrativeStructureMetrics | null;
  emotion_stats: EmotionStatsMetrics | null;
  character_stats: CharacterStatsMetrics | null;
  style_stats: StyleStatsMetrics | null;
  chapter_metrics: ChapterMetricsResponse | null;
  topics: Topic[];
  diagnosis: DiagnosisResult | null;
  emotion_trend: EmotionTrendWindow[];
}

/** 节奏张力 tab：段落曲线 + 叙事结构高潮参数 */
export interface RhythmTabResponse {
  run_id: string;
  curves: ParagraphCurvePoint[];
  narrative_structure: NarrativeStructureMetrics | null;
}

/** 功能与焦点 tab：角色功能分布 + 诊断焦点结构切片 */
export interface CharacterFunctionTabResponse {
  run_id: string;
  characters: Character[];
  focus_structure: "single" | "dual" | "ensemble" | null;
  focus_characters: string[] | null;
  arc_scores: Record<string, number> | null;
}

/** 图谱页登场次数切片 */
export interface CharacterAppearance {
  name: string;
  appearance_count: number;
}

/** 图结构指标（PageRank/HITS/Louvain，查询时计算） */
export interface GraphAlgorithmMetrics {
  run_id: string;
  unavailable_reason: string | null;
  algorithm: Record<string, unknown>;
  pagerank: Record<string, number>;
  hits: Record<string, unknown>;
  communities: Record<string, unknown>;
}

/** 图谱 tab：图快照 + 登场次数 + 图算法指标 + 变化总数 */
export interface GraphNetworkTabResponse {
  run_id: string;
  snapshot: GraphData | null;
  character_appearances: CharacterAppearance[];
  graph_metrics: GraphAlgorithmMetrics | null;
  change_total: number;
  unavailable_reason: string | null;
}

// 主题全量分布（赛道 D 单源端点：演进/迁移/情绪 tab 数据源）

export interface TopicSeriesPoint {
  paragraph_id: number;
  chapter_id: number;
  chapter_sequence: number;
  start_position: number;
  token_count: number;
  /** 完整 K 维权重，下标即 topic_id */
  weights: number[];
}

export interface TopicSeriesResponse {
  run_id: string;
  model: TopicModelMetaInfo | null;
  num_topics: number | null;
  points: TopicSeriesPoint[];
  unavailable_reason: string | null;
}

export interface TopicShiftConfig {
  window_size: number;
  min_tokens_per_window: number;
  score_threshold: number;
  max_candidates: number;
}

export interface TopicShiftCandidate {
  position: number;
  paragraph_start: number;
  paragraph_end: number;
  /** 以 2 为底的 JS 散度，值域 [0,1] */
  score: number;
  window_token_total: number;
}

export interface TopicShiftResponse {
  candidates: TopicShiftCandidate[];
  config: TopicShiftConfig;
  unavailable_reason: string | null;
}

export interface TopicEmotionEntry {
  topic_id: number;
  emotion: number | null;
  weighted_token_total: number | null;
}

export interface TopicEmotionResponse {
  run_id: string;
  model: TopicModelMetaInfo | null;
  emotion: TopicEmotionEntry[];
  unavailable_reason: string | null;
}

// 语言特征（赛道 A/B/C 单源端点：词法句法/词向量 tab 数据源）

export interface LinguisticGroupStats {
  token_total: number | null;
  sentence_total: number | null;
  word_length_ratios: Record<string, number> | null;
  pos_ratios: Record<string, number> | null;
  sentence_pattern_ratios: Record<string, number> | null;
  avg_dependency_depth: number | null;
  max_dependency_depth: number | null;
  dependency_relation_ratios: Record<string, number> | null;
  dependency_root_count: number | null;
  // 段落级监督边界（按书拟合；标签不足/类别单一时为 null，跨书口径不可比）
  boundary_pos_score_sum: number | null;
  boundary_neg_score_sum: number | null;
}

export interface ChapterLinguisticStats extends LinguisticGroupStats {
  chapter_id: number;
}

export interface LinguisticFeaturesResponse extends LinguisticGroupStats {
  run_id: string;
  paragraph_count: number;
  chapters: ChapterLinguisticStats[];
  unavailable_reason: string | null;
}

export interface Word2VecModelInfo {
  embedding_dimension: number;
  vocabulary_size: number;
  artifact_scope: string;
}

export interface PosCoverageEntry {
  pos_group: string;
  source_token_total: number;
  in_vocabulary_token_total: number;
  coverage_ratio: number | null;
}

export interface PosCentroidEntry {
  pos_group: string;
  weighted_token_total: number;
  embedding_vector: number[];
}

export interface Word2VecStatsResponse {
  run_id: string;
  model: Word2VecModelInfo | null;
  pos_coverage: PosCoverageEntry[];
  pos_centroids: PosCentroidEntry[];
  /** POS 质心余弦相似度矩阵，行序与 pos_centroids 一致；质心不足 2 组时为 null */
  pos_similarity_matrix: number[][] | null;
  unavailable_reason: string | null;
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

// 设置模块（/api/settings）

export type SettingFieldType = "number" | "integer" | "boolean" | "enum" | "string";

export interface SettingSectionSpec {
  id: string;
  title: string;
  description: string;
  order: number;
}

export interface SettingFieldSpec {
  /** settings.json 中的结构化路径，如 ["models", "annotation", "temperature"] */
  path: string[];
  field_type: SettingFieldType;
  label: string;
  description: string;
  min_value: number | null;
  max_value: number | null;
  step: number | null;
  enum_values: string[];
  nullable: boolean;
  editable: boolean;
}

export interface SettingsSchemaResponse {
  sections: SettingSectionSpec[];
  fields: SettingFieldSpec[];
}

export type SettingSource = "default" | "file";

export interface SettingsViewResponse {
  /** 当前生效值（默认值 ← settings.json ← env 凭据）；api_key 为打码值（"••••" 前缀） */
  values: Record<string, unknown>;
  defaults: Record<string, unknown>;
  /** 键为 path.join("/") */
  sources: Record<string, SettingSource>;
}

export interface TaskEnvPatch {
  base_url?: string | null;
  model?: string | null;
  /** null/缺省=不修改；""=整组清空；非空=设置 */
  api_key?: string | null;
}

export interface ModelEnvUpdate {
  model?: TaskEnvPatch | null;
  embedding_model?: TaskEnvPatch | null;
  ltp_model_dir?: string | null;
}

export interface ModelProviderTestResponse {
  ok: boolean;
  latency_ms: number | null;
  model_ids: string[];
  error: string | null;
}
