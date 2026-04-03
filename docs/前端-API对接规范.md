# 前端 API 对接规范

> **版本**: v1.0  
> **创建时间**: 2026-04-02  
> **定位**: 前后端接口对接约定，包括请求规范、数据流映射、TypeScript 类型定义、错误处理

---

## 一、基础约定

### 1.1 API 地址

| 环境 | 配置 |
|------|------|
| 开发环境 | `VITE_API_BASE_URL=http://localhost:8000` |
| 生产环境 | 通过 nginx 反向代理，前端使用相对路径 `/api` |

### 1.2 Axios 实例配置

```typescript
// api/client.ts
import axios from "axios";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "",
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// 响应拦截器：统一错误处理
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const { status, data } = error.response;
      // 后端统一错误格式: { detail, error_type, status_code }
      const message = data?.detail || `请求失败 (${status})`;
      console.error(`[API Error] ${status}: ${message}`);
    }
    return Promise.reject(error);
  }
);
```

### 1.3 请求规范

| 规范 | 说明 |
|------|------|
| 前缀 | 所有接口统一前缀 `/api` |
| 路径参数 | `novel_id`, `task_id` 直接嵌入路径或查询参数 |
| 查询参数 | `task_id` 通过 `?task_id=xxx` 传递 |
| 文件上传 | `multipart/form-data`，字段名 `file` |
| 响应格式 | JSON |

---

## 二、TypeScript 类型定义

以下类型定义对应后端 `src/api/models/responses.py` 中的 Pydantic 模型。

```typescript
// api/types.ts

// ========== 小说管理 ==========

export interface NovelInfo {
  novel_id: string;
  filename: string;
  status?: string;
  created_at?: string;
}

export interface UploadResponse {
  novel_id: string;
  filename: string;
  status: string;   // "uploaded"
  message: string;
}

// ========== 分析任务 ==========

export type TaskStatus = "pending" | "running" | "completed" | "failed";

export interface AnalyzeResponse {
  novel_id: string;
  task_id: string;
  status: TaskStatus;
  message: string;
}

export interface ReanalyzeResponse {
  novel_id: string;
  task_id: string;
  status: TaskStatus;
  message: string;
}

export interface TaskInfo {
  task_id: string;
  novel_id: string;
  status: string;
  created_at?: string;
}

export interface TaskListResponse {
  novel_id: string;
  tasks: TaskInfo[];
}

export interface StatusResponse {
  novel_id: string;
  task_id?: string;
  status: TaskStatus;
  progress: number;    // 0-100
  stage?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
}

// ========== 曲线数据 ==========

export interface ChunkCurvePoint {
  chunk_id: number;
  pos_density?: number;
  neg_density?: number;
  net_density?: number;
  smoothed_density?: number;
  tension_proxy?: number;
  tension_composite?: number;
}

// ========== 角色数据 ==========

export interface CharacterStats {
  name: string;
  appearance_count: number;
  dominant_role_function: string;
  role_function_distribution: Record<string, number>;
  dominant_role_ratio: number;
  protagonist_score?: number;
  is_protagonist?: boolean;
  avg_emotion_score?: number;
}

// ========== 主题数据 ==========

export interface TopicInfo {
  topic_id: number;
  words: string[];
  weight: number;
}

// ========== 诊断数据 ==========

export interface DiagnosisResult {
  foreshadow_rate?: number;
  arc_scores?: number[] | Record<string, number>;
  narrative_type?: string;
  topic_labels?: string[];
  diagnosis?: string;
  value_logic_type?: string;
  value_logic_reason?: string;
  power_stance_score?: number;
  power_stance_reason?: string;
  common_people_dignity?: number;
  dignity_reason?: string;
  cultural_depth_score?: number;
  cultural_depth_reason?: string;
  narrative_arc_type?: string;
  protagonist?: string;
  main_characters?: string[];
  core_cast?: string[];
  theme_color?: string;              // 新增：主题色（十六进制）
}

// ========== 知识图谱 ==========

export interface GraphNode {
  id: string;
  type: string;    // "character" | "group" | "organization"
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface GraphSnapshot {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ========== 叙事时间轴 ==========

export interface RelationChangeEvent {
  from_char: string;
  to_char: string;
  relation_type: string;
  change_type: string;
  evidence?: string;
}

export interface TimelinePhase {
  name: string;     // "引入期" | "发展期" | "高潮期" | "收束期"
  start: number;
  end: number;
  ratio: number;
}

export interface TimelineNode {
  chunk_id: number;
  progress: number;
  importance_score: number;
  level: number;          // 1=重要, 2=较重要, 3=一般
  event: string;
  characters: string[];
  is_pivot: boolean;
  is_cliffhanger: boolean;
  tension_percentile: number;
  node_type: string;      // "pivot" | "cliffhanger" | "character_entry" | "character_exit" | "relation_change" | "normal"
  relation_changes?: RelationChangeEvent[];
  character_entries?: string[];
  character_exits?: string[];
}

export interface TimelineMeta {
  novel_id: string;
  novel_name: string;
  total_chunks: number;
}

export interface TimelineResponse {
  meta: TimelineMeta;
  phases: TimelinePhase[];
  nodes: TimelineNode[];
  tension_curve?: number[];
}

// ========== 聚合指标 ==========

export interface NarrativeStructureStats {
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

export interface EmotionStats {
  pos_neg_ratio?: number;
  positive_ratio?: number;
  negative_ratio?: number;
  neutral_ratio?: number;
  recovery_speed?: number;
  pivot_moment_density?: number;
  lexical_emotion_trend?: string;   // "rising" | "falling" | "stable" | "volatile"
}

export interface CharacterStatsAggregate {
  network_density?: number;
  protagonist_betweenness?: number;
  greimas_coverage?: number;
  function_coverage_distribution?: Record<string, number>;
  antagonist_strength_gap?: number;
  relation_change_freq?: number;
  degree_centrality?: Record<string, number>;
}

export interface StyleStats {
  tone_distribution?: Record<string, number>;
  vocab_breadth?: number;
  avg_word_len?: number;
  sent_len_std?: number;
  dialogue_ratio?: number;
  function_word_vector?: Record<string, number>;
  category_density?: Record<string, number>;
}

export interface CultureStats {
  idiom_density?: number;
  classical_sentence_ratio?: number;
  imagery_density?: number;
}

// ========== 错误响应 ==========

export interface ErrorResponse {
  detail: string;
  error_type: string;
  status_code: number;
}

// ========== 批量操作 ==========

export interface BatchDeleteResponse {
  success: boolean;
  message: string;
  deleted_count: number;
  failed_count: number;
  deleted_ids: string[];
  failed_ids: Array<{ [key: string]: string }>;
}
```

---

## 三、API 函数定义

### 3.1 小说管理

```typescript
// api/novels.ts
import { apiClient } from "./client";
import type { NovelInfo, UploadResponse, BatchDeleteResponse } from "./types";

/** 列出所有小说 */
export async function fetchNovels(): Promise<NovelInfo[]> {
  const { data } = await apiClient.get("/api/novels/");
  return data;
}

/** 上传小说文件 */
export async function uploadNovel(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post("/api/novels/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/** 删除小说 */
export async function deleteNovel(novelId: string): Promise<void> {
  await apiClient.delete(`/api/novels/${novelId}`);
}

/** 批量删除小说 */
export async function batchDeleteNovels(novelIds: string[]): Promise<BatchDeleteResponse> {
  const { data } = await apiClient.post("/api/novels/batch-delete", { novel_ids: novelIds });
  return data;
}
```

### 3.2 分析任务

```typescript
// api/analysis.ts
import { apiClient } from "./client";
import type {
  AnalyzeResponse,
  ReanalyzeResponse,
  StatusResponse,
  TaskListResponse,
  BatchDeleteResponse,
} from "./types";

/** 启动分析 */
export async function startAnalysis(
  novelId: string,
  taskId?: string
): Promise<AnalyzeResponse> {
  const { data } = await apiClient.post(`/api/novels/${novelId}/analyze`, {
    task_id: taskId ?? null,
  });
  return data;
}

/** 重新分析 */
export async function startReanalysis(
  novelId: string,
  options?: {
    force_preprocess?: boolean;
    force_annotate?: boolean;
    force_aggregate?: boolean;
    force_topic_model?: boolean;
    force_diagnose?: boolean;
    num_topics?: number;
    label?: string;
  }
): Promise<ReanalyzeResponse> {
  const { data } = await apiClient.post(`/api/novels/${novelId}/reanalyze`, options ?? {});
  return data;
}

/** 查询分析状态 */
export async function fetchStatus(
  novelId: string,
  taskId?: string
): Promise<StatusResponse> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/status`, {
    params: taskId ? { task_id: taskId } : {},
  });
  return data;
}

/** 获取任务列表 */
export async function fetchTasks(novelId: string): Promise<TaskListResponse> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/tasks`);
  return data;
}

/** 删除任务 */
export async function deleteTask(novelId: string, taskId: string): Promise<void> {
  await apiClient.delete(`/api/novels/${novelId}/tasks/${taskId}`);
}

/** 批量删除任务 */
export async function batchDeleteTasks(
  novelId: string,
  taskIds: string[]
): Promise<BatchDeleteResponse> {
  const { data } = await apiClient.post(`/api/novels/${novelId}/tasks/batch-delete`, {
    task_ids: taskIds,
  });
  return data;
}
```

### 3.3 结果数据

```typescript
// api/results.ts
import { apiClient } from "./client";
import type {
  ChunkCurvePoint,
  CharacterStats,
  TopicInfo,
  DiagnosisResult,
  GraphSnapshot,
  TimelineResponse,
  NarrativeStructureStats,
  EmotionStats,
  CharacterStatsAggregate,
  StyleStats,
  CultureStats,
} from "./types";

// ---- 基础结果数据 ----

/** 获取分块曲线（情绪 + 节奏） */
export async function fetchChunkCurves(
  novelId: string,
  taskId: string
): Promise<ChunkCurvePoint[]> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/chunk-curves`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取角色统计 */
export async function fetchCharacters(
  novelId: string,
  taskId: string
): Promise<CharacterStats[]> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/characters`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取主题分布 */
export async function fetchTopics(
  novelId: string,
  taskId: string
): Promise<TopicInfo[]> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/topics`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取诊断数据 */
export async function fetchDiagnosis(
  novelId: string,
  taskId: string
): Promise<DiagnosisResult> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/diagnosis`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取知识图谱 */
export async function fetchGraph(
  novelId: string,
  taskId: string
): Promise<GraphSnapshot> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/graph`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取叙事时间轴 */
export async function fetchTimeline(
  novelId: string,
  taskId: string,
  options?: { include_curve?: boolean; max_level?: number }
): Promise<TimelineResponse> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/timeline`, {
    params: {
      task_id: taskId,
      include_curve: options?.include_curve ?? false,
      max_level: options?.max_level ?? 3,
    },
  });
  return data;
}

// ---- 聚合指标 ----

/** 获取叙事结构指标 */
export async function fetchNarrativeStructure(
  novelId: string,
  taskId: string
): Promise<NarrativeStructureStats> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/narrative-structure`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 获取情感统计指标 */
export async function fetchEmotionStats(
  novelId: string,
  taskId: string
): Promise<EmotionStats> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/emotion-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 获取人物统计指标 */
export async function fetchCharacterStatsAggregate(
  novelId: string,
  taskId: string
): Promise<CharacterStatsAggregate> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/character-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 获取风格统计指标 */
export async function fetchStyleStats(
  novelId: string,
  taskId: string
): Promise<StyleStats> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/style-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 获取文化统计指标 */
export async function fetchCultureStats(
  novelId: string,
  taskId: string
): Promise<CultureStats> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/culture-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}
```

---

## 四、TanStack Query 集成

### 4.1 Query Key 设计

```typescript
// Query Key 命名规范
const queryKeys = {
  novels: {
    all:      ["novels"] as const,
    detail:   (id: string) => ["novels", id] as const,
    tasks:    (id: string) => ["novels", id, "tasks"] as const,
    status:   (id: string, taskId: string) => ["novels", id, "status", taskId] as const,
  },
  results: {
    curves:     (id: string, taskId: string) => ["results", id, taskId, "curves"] as const,
    characters: (id: string, taskId: string) => ["results", id, taskId, "characters"] as const,
    topics:     (id: string, taskId: string) => ["results", id, taskId, "topics"] as const,
    diagnosis:  (id: string, taskId: string) => ["results", id, taskId, "diagnosis"] as const,
    graph:      (id: string, taskId: string) => ["results", id, taskId, "graph"] as const,
    timeline:   (id: string, taskId: string) => ["results", id, taskId, "timeline"] as const,
  },
  metrics: {
    narrative:  (id: string, taskId: string) => ["metrics", id, taskId, "narrative"] as const,
    emotion:    (id: string, taskId: string) => ["metrics", id, taskId, "emotion"] as const,
    character:  (id: string, taskId: string) => ["metrics", id, taskId, "character"] as const,
    style:      (id: string, taskId: string) => ["metrics", id, taskId, "style"] as const,
    culture:    (id: string, taskId: string) => ["metrics", id, taskId, "culture"] as const,
  },
};
```

### 4.2 自定义 Hooks 示例

```typescript
// hooks/useAnalysisStatus.ts
import { useQuery } from "@tanstack/react-query";
import { fetchStatus } from "@/api/analysis";

/**
 * 分析状态轮询 Hook
 * - 任务运行中时每 3 秒轮询一次
 * - 任务完成/失败后停止轮询
 */
export function useAnalysisStatus(novelId: string, taskId: string) {
  return useQuery({
    queryKey: ["novels", novelId, "status", taskId],
    queryFn: () => fetchStatus(novelId, taskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "running" || status === "pending") return 3000;
      return false; // 停止轮询
    },
    enabled: !!novelId && !!taskId,
  });
}
```

```typescript
// hooks/useDiagnosis.ts
import { useQuery } from "@tanstack/react-query";
import { fetchDiagnosis } from "@/api/results";

export function useDiagnosis(novelId: string, taskId: string) {
  return useQuery({
    queryKey: ["results", novelId, taskId, "diagnosis"],
    queryFn: () => fetchDiagnosis(novelId, taskId),
    enabled: !!novelId && !!taskId,
    staleTime: 5 * 60 * 1000,   // 5 分钟内不重新请求（分析结果不会变）
  });
}
```

### 4.3 缓存策略

| 数据类型 | staleTime | 说明 |
|---------|-----------|------|
| 小说列表 | 30s | 可能有新上传 |
| 任务列表 | 30s | 可能有新任务或状态变更 |
| 分析状态 | 0（轮询模式） | 运行中实时刷新 |
| 曲线/角色/主题等结果数据 | 5min | 分析完成后数据不变 |
| 诊断数据 | 5min | 同上 |
| 聚合指标 | 5min | 同上 |
| 时间轴 | 5min | 同上 |

---

## 五、各页面数据流映射

### 5.1 HomePage 数据流

```
组件挂载
  │
  ├─▶ useQuery(["novels"]) ─── fetchNovels() ─── GET /api/novels/
  │     └─▶ NovelGrid 渲染小说卡片列表
  │
  ├─▶ [用户上传文件]
  │     └─▶ useMutation ─── uploadNovel(file) ─── POST /api/novels/upload
  │           └─▶ invalidateQueries(["novels"])  // 刷新列表
  │
  ├─▶ [用户点击"分析"]
  │     └─▶ useMutation ─── startAnalysis(novelId) ─── POST .../analyze
  │           └─▶ 返回 task_id，开始状态轮询
  │
  └─▶ [分析进行中]
        └─▶ useAnalysisStatus(novelId, taskId) ─── 轮询 GET .../status
              └─▶ 更新 NovelCard 上的进度环
```

### 5.2 NovelDetailPage 数据流

```
组件挂载（已知 novelId，用户选择/默认 taskId）
  │
  ├─▶ useQuery(tasks) ──────── fetchTasks() ─── GET .../tasks
  │     └─▶ 填充 TaskSelector
  │
  ├─▶ useDiagnosis() ───────── fetchDiagnosis() ─── GET .../diagnosis
  │     ├─▶ 提取 theme_color → useThemeStore.setSeedColor()  ★ 触发主题色变更
  │     └─▶ DiagnosisSummaryCard 渲染
  │
  ├─▶ useQuery(narrative) ──── fetchNarrativeStructure() ─── GET .../metrics/narrative-structure
  │     └─▶ DimensionMiniCard(叙事) + NarrativeStructureBar（三幕比例 + 事件密度）
  ├─▶ useQuery(emotion) ────── fetchEmotionStats() ─── GET .../metrics/emotion-stats
  │     └─▶ DimensionMiniCard(情感)（pos_neg_ratio）
  ├─▶ useQuery(character) ──── fetchCharacterStatsAggregate() ─── GET .../metrics/character-stats
  │     └─▶ DimensionMiniCard(人物)（network_density）
  ├─▶ useQuery(style) ──────── fetchStyleStats() ─── GET .../metrics/style-stats
  │     └─▶ DimensionMiniCard(风格)（vocab_breadth + dialogue_ratio）
  ├─▶ useQuery(culture) ────── fetchCultureStats() ─── GET .../metrics/culture-stats
  │     └─▶ DimensionMiniCard(文化)（idiom_density + classical_sentence_ratio + imagery_density）
  │
  └─▶ useQuery(curves) ─────── fetchChunkCurves() ─── GET .../chunk-curves
        └─▶ MiniCurvePreview 缩略图
```

**关键流程：主题色触发**

```
diagnosis 请求返回
  └─▶ response.theme_color 存在且合法
        └─▶ themeStore.setSeedColor(response.theme_color)
              └─▶ useNovelTheme() effect 触发
                    └─▶ generateThemePalette() 生成色板
                          └─▶ 写入 CSS 变量到 :root
                                └─▶ 全页面颜色自动更新
```

### 5.3 CurvesPage 数据流

```
组件挂载
  │
  ├─▶ useQuery(curves) ────── fetchChunkCurves() ─── GET .../chunk-curves
  │     └─▶ 拆分为 emotion 和 rhythm 两组数据
  │           ├─▶ EmotionCurveChart(pos_density, neg_density, net_density, smoothed_density)
  │           └─▶ RhythmCurveChart(tension_proxy, tension_composite)
  │
  └─▶ useQuery(narrative) ── fetchNarrativeStructure() ─── GET .../metrics/narrative-structure
        └─▶ 提取 act1_ratio/act2_ratio + climax_positions
              └─▶ RhythmCurveChart 叠加三幕分界线和高潮标注
```

### 5.4 GraphPage 数据流

```
组件挂载
  │
  ├─▶ useQuery(graph) ──── fetchGraph() ─── GET .../graph
  │     └─▶ 转换为 ForceGraph 数据格式
  │           └─▶ ForceGraph 渲染力导向图
  │
  └─▶ useQuery(characters) ── fetchCharacters() ─── GET .../characters
        └─▶ 补充节点属性（出场次数 → 节点大小）
```

### 5.5 TimelinePage 数据流

```
组件挂载
  │
  └─▶ useQuery(timeline) ── fetchTimeline(include_curve=true, max_level=3)
        │                       └── GET .../timeline?task_id=...&include_curve=true&max_level=3
        │
        ├─▶ response.phases → PhaseBar
        ├─▶ response.nodes → TimelineTrack + TimelineNode
        └─▶ response.tension_curve → TensionOverlay (可选)
```

---

## 六、错误处理规范

### 6.1 后端错误格式

```json
{
  "detail": "小说不存在: 10960c77",
  "error_type": "NovelNotFoundError",
  "status_code": 404
}
```

### 6.2 前端错误处理策略

| HTTP 状态码 | error_type | 前端处理 |
|------------|-----------|---------|
| 404 | `NovelNotFoundError` | 显示"小说不存在"提示，引导返回首页 |
| 400 | `AnalysisNotCompleteError` | 显示"分析未完成"提示，显示当前状态 |
| 400 | `FileUploadError` | 上传弹窗中显示错误信息 |
| 500 | `AnalysisError` | Toast 错误提示 + 建议重试 |
| 网络错误 | - | Toast "网络连接失败" + 自动重试（TanStack Query 默认3次） |
| 超时 | - | Toast "请求超时" + 手动重试按钮 |

### 6.3 全局错误边界

```typescript
// 使用 React Error Boundary 包裹页面级组件
// 捕获渲染阶段异常，显示友好错误页面而非白屏

<ErrorBoundary fallback={<ErrorFallback />}>
  <PageContent />
</ErrorBoundary>
```

### 6.4 TanStack Query 全局错误处理

```typescript
// main.tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 3,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
      staleTime: 30 * 1000,
    },
    mutations: {
      onError: (error) => {
        // 全局 Toast 错误提示
        toast.error(getErrorMessage(error));
      },
    },
  },
});
```

---

## 七、API 接口完整索引

快速查找各页面使用的接口。

| 页面 | 接口 | 方法 | 说明 |
|------|------|------|------|
| **HomePage** | `/api/novels/` | GET | 小说列表 |
| | `/api/novels/upload` | POST | 上传小说 |
| | `/api/novels/{id}/analyze` | POST | 启动分析 |
| | `/api/novels/{id}/status` | GET | 轮询状态 |
| | `/api/novels/{id}` | DELETE | 删除小说 |
| **NovelDetailPage** | `/api/novels/{id}/tasks` | GET | 任务列表 |
| | `/api/novels/{id}/diagnosis` | GET | 诊断数据 + 主题色 |
| | `/api/novels/{id}/metrics/*` | GET | 五维聚合指标（5个接口） |
| | `/api/novels/{id}/chunk-curves` | GET | 曲线缩略 |
| **CurvesPage** | `/api/novels/{id}/chunk-curves` | GET | 完整曲线 |
| | `/api/novels/{id}/metrics/narrative-structure` | GET | 三幕分界 |
| **CharactersPage** | `/api/novels/{id}/characters` | GET | 角色列表 |
| | `/api/novels/{id}/diagnosis` | GET | 主角/弧线分 |
| **GraphPage** | `/api/novels/{id}/graph` | GET | 图谱数据 |
| | `/api/novels/{id}/characters` | GET | 补充节点属性 |
| **TopicsPage** | `/api/novels/{id}/topics` | GET | 主题列表 |
| | `/api/novels/{id}/diagnosis` | GET | 主题标签 |
| **TimelinePage** | `/api/novels/{id}/timeline` | GET | 时间轴 |
| **DiagnosisPage** | `/api/novels/{id}/diagnosis` | GET | 完整诊断 |

---

## 八、关联文档

| 文档 | 说明 |
|------|------|
| [前端开发总文档](./前端开发总文档.md) | 技术栈、项目结构、开发规范 |
| [动态主题色系统设计](./前端-动态主题色系统设计.md) | 种子色派生算法、CSS 变量体系 |
| [页面与组件设计](./前端-页面与组件设计.md) | 每个页面的布局、组件拆分、交互细节 |
| [API 文档](./API文档.md) | 后端 API 完整接口文档（已有） |
