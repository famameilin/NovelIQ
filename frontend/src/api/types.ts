// ============================================================
// Novel
// ============================================================

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

// ============================================================
// Analysis Task
// ============================================================

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
  created_at: string;
  completed_at?: string;
  error?: string;
}

export interface AnalysisStartResponse {
  novel_id: string;
  task_id: string;
  message: string;
}

// ============================================================
// Characters
// ============================================================

export interface Character {
  name: string;
  appearance_count: number;
  dominant_role_function: string;
  role_function_distribution?: Record<string, number>;
  dominant_role_ratio?: number;
  protagonist_score?: number | null;
  is_protagonist?: boolean | null;
  avg_emotion_score?: number | null;
}

// ============================================================
// Chunk Curves
// ============================================================

export interface ChunkCurvePoint {
  chunk_id: number;
  pos_density: number | null;
  neg_density: number | null;
  net_density: number | null;
  smoothed_density: number | null;
  tension_proxy: number | null;
  tension_composite?: number | null;
}

// ============================================================
// Topics
// ============================================================

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-C 主题分布
// 说明: LDA 主题建模结果类型定义。label 字段为可选预留字段，
//       后端当前不返回，供未来 LLM 诊断阶段生成主题命名时使用。

export interface Topic {
  topic_id: number;
  words: string[];
  weight: number;
  // 可选字段：后端暂未返回，预留供 LLM 诊断阶段生成主题命名时使用
  label?: string;
}

// ============================================================
// Diagnosis
// ============================================================

export interface DiagnosisResult {
  narrative_type?: string;
  foreshadow_rate?: number;
  protagonist?: string;
  narrative_arc_type?: string;
  arc_scores?: Record<string, number>;
  diagnosis?: string;
  value_logic_type?: string;
  value_logic_reason?: string;
  power_stance_score?: number;
  power_stance_reason?: string;
  common_people_dignity?: number;
  dignity_reason?: string;
  cultural_depth_score?: number;
  cultural_depth_reason?: string;
  topic_labels?: string[];
  core_cast?: string[];
  main_characters?: string[];
  theme_color?: string;
}

// ============================================================
// Knowledge Graph
// ============================================================

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-A 人物关系图谱 API 类型定义
// 说明: 更新图谱节点类型，添加实体详细信息字段

export interface GraphNode {
  entity_id: string;
  name: string;
  entity_type: string;
  first_seen_chunk?: number;
  last_seen_chunk?: number;
  role?: string;
  status?: string;
}

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-A 人物关系图谱 API 类型定义
// 说明: 更新图谱边类型，relation_type 改为可选

export interface GraphEdge {
  source: string;
  target: string;
  relation_type?: string;
  weight?: number;
}

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-A 人物关系图谱 API 类型定义
// 说明: 添加图谱事件类型定义

export interface GraphEvent {
  event_id: string;
  event_type: string;
  source_entity: string;
  target_entity: string;
  relation_type?: string;
  chunk_index?: number;
  timestamp?: string;
}

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-A 人物关系图谱 API 类型定义
// 说明: 更新图谱数据类型，添加 events, summary, quality 字段

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  events?: GraphEvent[];
  summary?: Record<string, unknown>;
  quality?: Record<string, unknown>;
}

// ============================================================
// Force Graph Runtime Types (G6)
// ============================================================

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-A 人物关系图谱
// 说明: 运行时节点对象，包含力模拟/布局后的坐标

export interface GraphNodeObject extends GraphNode {
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-A 人物关系图谱
// 说明: 运行时边对象（G6 兼容格式）

export interface GraphLinkObject {
  source: string | GraphNodeObject;
  target: string | GraphNodeObject;
  relation_type?: string;
  weight?: number;
}

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: 修复 ForceGraph TypeScript 类型错误
// 说明: 供 ForceGraph 组件使用的图谱数据类型，使用 links 而不是 edges

export interface ForceGraphData {
  nodes: GraphNodeObject[];
  links: GraphLinkObject[];
  events?: GraphEvent[];
  summary?: Record<string, unknown>;
  quality?: Record<string, unknown>;
}

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-A 人物关系图谱
// 说明: ForceGraph 组件 Props 类型定义

export interface ForceGraphProps {
  data: GraphData;
  onNodeClick: (node: GraphNodeObject) => void;
  searchQuery: string;
  relationFilter: Set<string>;
  appearanceCountMap?: Map<string, number>;
  className?: string;
}

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-A 人物关系图谱
// 说明: ForceGraph 组件暴露的方法句柄

export interface ForceGraphHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fitToScreen: () => void;
  center: () => void;
}

// ============================================================
// Timeline
// ============================================================

// 创建时间: 2026-04-05
// 创建者: GLM-5
// 任务: Phase 2-B 叙事时间轴
// 说明: 更新 Timeline 类型定义，与后端 API 响应结构对齐

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

export interface RelationChangeEvent {
  from_char: string;
  to_char: string;
  relation_type: string;
  change_type: string;
  evidence?: string;
}

export interface TimelineNode {
  chunk_id: number;
  progress: number;
  importance_score: number;
  level: 1 | 2 | 3;
  event: string;
  characters: string[];
  is_pivot: boolean;
  is_cliffhanger: boolean;
  tension_percentile: number;
  node_type: "plot" | "character_entry" | "character_exit" | "relation_change";
  relation_changes?: RelationChangeEvent[];
  character_entries?: string[];
  character_exits?: string[];
}

export interface TimelineResponse {
  meta: TimelineMeta;
  phases: TimelinePhase[];
  nodes: TimelineNode[];
  tension_curve?: number[];
}

// ============================================================
// Metrics
// ============================================================

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
  total_characters: number;
  protagonist_count: number;
  network_density: number;
  greimas_coverage: number;
}

export interface StyleStatsMetrics {
  vocab_breadth: number;
  avg_sent_len: number;
  dialogue_ratio: number;
}

export interface CultureStatsMetrics {
  idiom_density: number;
  imagery_density: number;
  classical_sentence_ratio: number;
  allusion_density: number;
}

// ============================================================
// Common
// ============================================================

export interface ApiError {
  detail: string;
}

// ============================================================
// Pagination
// ============================================================

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
