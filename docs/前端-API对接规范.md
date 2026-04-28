# 前端 API 对接规范

> **版本**: v1.0  
> **创建时间**: 2026-04-02  
> **定位**: 前后端接口对接约定，包括请求规范、数据流映射、TypeScript 类型定义、错误处理

---

## 一、基础约定

### 1.1 API 地址

| 环境 | 配置 |
|------|------|
| 开发环境 | 当前默认使用源码内 `appConfig.apiBaseUrl` |
| 生产环境 | 由部署层决定 `appConfig.apiBaseUrl`，不依赖 `VITE_*` 构建时注入 |

### 1.2 Axios 实例配置

```typescript
// api/client.ts
import axios from "axios";
import { appConfig } from "@/config";

export const apiClient = axios.create({
  baseURL: appConfig.apiBaseUrl,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// 说明：
// - 当前前端不依赖 VITE_API_BASE_URL
// - 结果链路的 409 可能返回结构化 detail={ code, message, reason }
// - 前端错误解析需兼容字符串 detail 与对象 detail 两种形状
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

以下类型定义为**当前前端 contract 摘要**。
完整 truth source 以 `frontend/src/api/types.ts` 为准。

```typescript
// ========== 小说管理 ==========

export interface Novel {
  novel_id: string;
  title: string;
  filename: string;
  author?: string;
  upload_time: string | null;
  file_size: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ========== 分析任务 ==========

export type TaskStatus =
  | "pending"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";

export interface AnalysisStartResponse {
  novel_id: string;
  task_id: string;
  message: string;
}

export interface TaskStatusResponse {
  novel_id: string;
  task_id: string;
  status: TaskStatus;
  progress: number;
  current_step: string;
  stage?: string;
  sub_stage?: string;
  current?: number;
  total?: number;
  message?: string;
  error?: string;
}

// ========== 主题与诊断 ==========

export interface Topic {
  topic_id: number;
  words: string[];
  weight: number;
  label?: string;
}

export interface DiagnosisResult {
  rerun_required?: boolean;
  rerun_reason?: string | null;
  narrative_type?: string | null;
  foreshadow_expectation?: number | null;
  narrative_arc_type?: string | null;
  arc_scores?: Record<string, number> | null;
  focus_structure?: "single" | "dual" | "ensemble" | null;
  focus_characters?: string[] | null;
  main_characters?: string[] | null;
  core_cast?: string[] | null;
  topic_labels?: string[] | null;
  theme_color?: string | null;
}

// ========== 图谱 ==========

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  events: GraphEvent[];
  events_page: GraphEventsPageInfo;
  summary: GraphPageSummary;
  quality: GraphPageQualityReport;
}

// ========== 时间轴 ==========

export interface TimelineResponse {
  meta: TimelineMeta;
  phases: TimelinePhase[];
  composite_nodes: TimelineCompositeNode[];
  atomic_nodes: TimelineNode[];
  tension_curve?: number[];
}

// ========== 错误 ==========

export interface ApiError {
  detail: string | { code: string; message: string; reason?: string };
  error_type?: string;
  status_code?: number;
}
```

---

## 三、API 函数定义

### 3.1 小说管理

```typescript
// api/novels.ts
import { apiClient } from "./client";
import type { NovelInfo, UploadResponse, BatchDeleteResponse } from "./types";

/** 分页列出小说 */
export async function getNovels(params: { page?: number; page_size?: number } = {}): Promise<PaginatedResponse<Novel>> {
  const { page = 1, page_size = 12 } = params;
  const { data } = await apiClient.get("/api/novels/", {
    params: { page, page_size },
  });
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
  AnalysisStartResponse,
  TaskStatusResponse,
  BatchDeleteTasksResponse,
} from "./types";

/** 创建并启动新任务 */
export async function createAnalysisTask(novelId: string): Promise<AnalysisStartResponse> {
  const { data } = await apiClient.post(`/api/novels/${novelId}/tasks`);
  return data;
}

/** 继续指定 pending/failed 任务 */
export async function resumeAnalysisTask(
  novelId: string,
  taskId: string
): Promise<AnalysisStartResponse> {
  const { data } = await apiClient.post(`/api/novels/${novelId}/tasks/${taskId}/resume`);
  return data;
}

/** 查询单任务状态 */
export async function getTaskStatus(novelId: string, taskId: string): Promise<TaskStatusResponse> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/tasks/${taskId}/status`);
  return data;
}

/** 获取任务列表 */
export async function getAnalysisTasks(novelId: string) {
  const { data } = await apiClient.get(`/api/novels/${novelId}/tasks`);
  return data.tasks;
}

/** 取消任务 */
export async function cancelAnalysisTask(novelId: string, taskId: string) {
  const { data } = await apiClient.post(`/api/novels/${novelId}/tasks/${taskId}/cancel`);
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
): Promise<BatchDeleteTasksResponse> {
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
  Character,
  Topic,
  DiagnosisResult,
  GraphData,
  GraphEventsPageResponse,
  TimelineResponse,
  NarrativeStructureMetrics,
  EmotionStatsMetrics,
  CharacterStatsMetrics,
  StyleStatsMetrics,
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
export async function getCharacters(
  novelId: string,
  taskId: string
): Promise<Character[]> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/characters`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取主题分布 */
export async function getTopics(
  novelId: string,
  taskId: string
): Promise<Topic[]> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/topics`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取诊断数据 */
export async function getDiagnosis(
  novelId: string,
  taskId: string
): Promise<DiagnosisResult> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/diagnosis`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取知识图谱 */
export async function getGraph(
  novelId: string,
  taskId: string
): Promise<GraphData> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/graph`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 获取图谱关系事件分页 */
export async function getGraphEvents(
  novelId: string,
  taskId: string,
  options?: { eventsCursor?: string | null; eventsLimit?: number }
): Promise<GraphEventsPageResponse> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/graph/events`, {
    params: {
      task_id: taskId,
      ...(options?.eventsCursor ? { events_cursor: options.eventsCursor } : {}),
      ...(options?.eventsLimit != null ? { events_limit: options.eventsLimit } : {}),
    },
  });
  return data;
}

/** 获取叙事时间轴 */
export async function getTimeline(
  novelId: string,
  taskId: string,
  options?: { includeCurve?: boolean }
): Promise<TimelineResponse> {
  const { data } = await apiClient.get(`/api/novels/${novelId}/timeline`, {
    params: {
      task_id: taskId,
      include_curve: options?.includeCurve ?? true,
    },
  });
  return data;
}

// ---- 聚合指标 ----

/** 获取叙事结构指标 */
export async function getNarrativeStructure(
  novelId: string,
  taskId: string
): Promise<NarrativeStructureMetrics> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/narrative-structure`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 获取情感统计指标 */
export async function getEmotionStats(
  novelId: string,
  taskId: string
): Promise<EmotionStatsMetrics> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/emotion-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 获取人物统计指标 */
export async function getCharacterStats(
  novelId: string,
  taskId: string
): Promise<CharacterStatsMetrics> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/character-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 获取风格统计指标 */
export async function getStyleStats(
  novelId: string,
  taskId: string
): Promise<StyleStatsMetrics> {
  const { data } = await apiClient.get(
    `/api/novels/${novelId}/metrics/style-stats`,
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
    status:   (id: string, taskId: string) => ["task-status", id, taskId] as const,
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
  },
};
```

### 4.2 自定义 Hooks 示例

```typescript
// hooks/useAnalysisStatus.ts
import { useQuery } from "@tanstack/react-query";
import { getTaskStatus } from "@/api/analysis";

/**
 * 分析状态轮询 Hook
 * - 任务运行中时每 3 秒轮询一次
 * - 任务完成/失败后停止轮询
 */
export function useAnalysisStatus(novelId: string, taskId: string) {
  return useQuery({
    queryKey: ["task-status", novelId, taskId],
    queryFn: () => getTaskStatus(novelId, taskId),
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
  ├─▶ useQuery(["novels", page]) ─── getNovels({ page, page_size }) ─── GET /api/novels/
  │     └─▶ 返回分页对象 { items, total, page, page_size, total_pages }
  │
  ├─▶ [用户上传文件]
  │     └─▶ useMutation ─── uploadNovel(file) ─── POST /api/novels/upload
  │           └─▶ invalidateQueries(["novels"])
  │
  └─▶ [悬浮/点击小说卡片]
        ├─▶ prefetchNovel() ─── GET /api/novels/
        └─▶ navigate("/novels/:novelId")
```

### 5.2 NovelDetailPage 数据流

```
组件挂载（已知 novelId，用户选择/默认 taskId）
  │
  ├─▶ useQuery(tasks) ──────── fetchTasks() ─── GET .../tasks
  │     └─▶ 填充 TaskSelector
  │
  ├─▶ useDiagnosis() ───────── fetchDiagnosis() ─── GET .../diagnosis
  │     ├─▶ 若 `theme_color` 合法，则切入任务主题
  │     └─▶ DiagnosisSummaryCard 渲染
  │
  ├─▶ useQuery(narrative) ──── fetchNarrativeStructure() ─── GET .../metrics/narrative-structure
  │     └─▶ DimensionMiniCard(叙事) + NarrativeStructureBar（三幕比例 + 事件密度）
  ├─▶ useQuery(emotion) ────── fetchEmotionStats() ─── GET .../metrics/emotion-stats
  │     └─▶ DimensionMiniCard(情感)（pos_neg_ratio）
  ├─▶ useQuery(character) ──── fetchCharacterStatsAggregate() ─── GET .../metrics/character-stats
  │     └─▶ DimensionMiniCard(人物)（network_density，字段名兼容，现语义为关系集中度）
  ├─▶ useQuery(style) ──────── fetchStyleStats() ─── GET .../metrics/style-stats
  │     └─▶ DimensionMiniCard(风格)（当前展示 vocab_breadth + dialogue_ratio）
  │
  └─▶ useQuery(curves) ─────── fetchChunkCurves() ─── GET .../chunk-curves
        └─▶ MiniCurvePreview 缩略图
```

> 设计说明：文化指标 `idiom_density` / `classical_sentence_ratio` / `imagery_density` 仍属于研究型聚合结果，但当前产品主界面第五维已切换为“主题内容”，因此前端不再定义 `CultureStats` 接口，也不再请求 `/metrics/culture-stats`。

**关键流程：主题色触发**

```
diagnosis 请求返回
  ├─▶ response.theme_color 存在且合法
  │     └─▶ themeStore.setSeedColor(response.theme_color)
  │           └─▶ useNovelTheme() effect 触发
  │                 └─▶ generateThemePalette() 生成色板
  │                       └─▶ 写入 CSS 变量到 :root
  │                             └─▶ 全页面颜色自动更新
  └─▶ response.theme_color 缺失 / 非法
        └─▶ 保持 neutral palette，不切到默认紫色任务主题
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
  ├─▶ useQuery(graph) ──── getGraph() ─── GET .../graph
  │     ├─▶ 主合同要求 nodes + edges + events + events_page + summary + quality
  │     ├─▶ 缺少 summary/quality/events_page 会被页面视为 contract break
  │     └─▶ 初始 events 交给图谱工作区渲染
  │
  ├─▶ useGraphEventPagination()
  │     └─▶ GET .../graph/events?events_cursor=...&events_limit=...
  │
  └─▶ useQuery(characters) ── getCharacters() ─── GET .../characters
        └─▶ 补充节点属性（出场次数 → 节点大小）
```

### 5.5 TimelinePage 数据流

```
组件挂载
  │
  └─▶ useQuery(timeline) ── getTimeline(includeCurve=true)
        │                    └── GET .../timeline?task_id=...&include_curve=true
        │
        ├─▶ response.phases → PhaseBar
        ├─▶ response.composite_nodes / atomic_nodes → TimelineTrack
        ├─▶ response.tension_curve → TensionOverlay
        └─▶ URL 本地状态：task_id / max_level / view / selected_node_id / selected_chunk / relation_event_id
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

或（结果链路 409）：

```json
{
  "detail": {
    "code": "diagnosis_rerun_required",
    "message": "当前结果需要重新分析",
    "reason": "focus_contract_incomplete"
  }
}
```

### 6.2 前端错误处理策略

| HTTP 状态码 | error_type | 前端处理 |
|------------|-----------|---------|
| 404 | `NovelNotFoundError` | 显示“小说不存在”提示，引导返回首页 |
| 400 | `AnalysisNotCompleteError` | 显示“分析未完成”提示，显示当前状态 |
| 400 | `FileUploadError` | 上传弹窗中显示错误信息 |
| 409 | `detail.code=diagnosis_rerun_required` | 进入 rerun-required UI，不继续渲染半成品页面 |
| 409 | `GraphReadinessError` | 图谱/时间轴结果不可读，提示重跑或等待主链完成 |
| 500 | `InternalServerError` / `AnalysisError` | Toast 错误提示 + 建议重试 |
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
| **HomePage** | `/api/novels/` | GET | 分页小说列表 |
| | `/api/novels/upload` | POST | 上传小说 |
| | `/api/novels/{id}` | DELETE | 删除小说 |
| **Task APIs** | `/api/novels/{id}/tasks` | POST | 创建并启动新任务 |
| | `/api/novels/{id}/tasks/{task_id}/resume` | POST | 继续 pending/failed 任务 |
| | `/api/novels/{id}/tasks/{task_id}/status` | GET | 查询单任务状态 |
| | `/api/novels/{id}/tasks/{task_id}/cancel` | POST | 取消任务 |
| **NovelDetailPage** | `/api/novels/{id}/tasks` | GET | 任务列表 |
| | `/api/novels/{id}/diagnosis` | GET | 诊断数据 + 主题色 |
| | `/api/novels/{id}/metrics/*` | GET | 五维聚合指标（5个接口） |
| | `/api/novels/{id}/chunk-curves` | GET | 曲线缩略 |
| **CurvesPage** | `/api/novels/{id}/chunk-curves` | GET | 完整曲线 |
| | `/api/novels/{id}/metrics/narrative-structure` | GET | 三幕分界 |
| **GraphPage** | `/api/novels/{id}/graph` | GET | graph snapshot（含 summary/quality/events_page） |
| | `/api/novels/{id}/graph/events` | GET | relation events 分页 |
| **TimelinePage** | `/api/novels/{id}/timeline` | GET | 双层节点时间轴 |
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
