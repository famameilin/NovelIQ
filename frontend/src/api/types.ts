// ============================================================
// Novel
// ============================================================

export interface Novel {
  id: string;
  title: string;
  filename: string;
  upload_time: string;
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
  | "chunking"
  | "annotating"
  | "aggregating"
  | "diagnosing"
  | "completed"
  | "failed";

export interface TaskStatusResponse {
  novel_id: string;
  task_id: string;
  status: TaskStatus;
  progress: number;
  current_step: string;
  error?: string;
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
  count: number;
  entity_type: string;
  dominant_function?: string;
  protagonist_score?: number;
  avg_sentiment?: number;
}

// ============================================================
// Chunk Curves
// ============================================================

export interface ChunkCurvePoint {
  chunk_index: number;
  positive_density: number;
  negative_density: number;
  net_density: number;
  smoothed_density: number;
  tension_proxy: number;
  tension_composite?: number;
}

// ============================================================
// Topics
// ============================================================

export interface Topic {
  topic_id: number;
  keywords: string[];
  weight: number;
  label?: string;
}

// ============================================================
// Diagnosis
// ============================================================

export interface DiagnosisResult {
  narrative_type?: string;
  foreshadow_rate?: number;
  protagonist?: string;
  arc_type?: string;
  arc_scores?: Record<string, number>;
  value_logic_type?: string;
  value_logic_reason?: string;
  power_stance?: number;
  power_stance_reason?: string;
  civilian_dignity?: number;
  civilian_dignity_reason?: string;
  cultural_depth?: number;
  topic_labels?: string[];
  core_cast?: string[];
  major_cast?: string[];
  theme_color?: string;
}

// ============================================================
// Knowledge Graph
// ============================================================

export interface GraphNode {
  id: string;
  name: string;
  entity_type: string;
  count?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation_type: string;
  weight?: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ============================================================
// Timeline
// ============================================================

export interface TimelinePhase {
  phase_name: string;
  start_ratio: number;
  end_ratio: number;
}

export interface TimelineNode {
  node_id: string;
  chunk_index: number;
  summary: string;
  importance_score: number;
  node_type: string;
  characters: string[];
  tension_percentile?: number;
}

export interface TimelineData {
  phases: TimelinePhase[];
  nodes: TimelineNode[];
  tension_curve?: number[];
}

// ============================================================
// Metrics
// ============================================================

export interface NarrativeStructureMetrics {
  act1_ratio: number;
  act2_ratio: number;
  act3_ratio: number;
  climax_positions: number[];
  cliffhanger_rate: number;
  middle_collapse_index: number;
}

export interface EmotionStatsMetrics {
  pivot_moment_density: number;
  recovery_speed: number;
  emotional_range: number;
  mean_sentiment: number;
}

export interface CharacterStatsMetrics {
  total_characters: number;
  protagonist_count: number;
  network_density: number;
  greimas_coverage: number;
}

export interface StyleStatsMetrics {
  vocab_breadth: number;
  mean_sentence_length: number;
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
