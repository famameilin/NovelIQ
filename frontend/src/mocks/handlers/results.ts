/**
 * MSW Handler — 分析结果：角色、情绪趋势、主题、诊断、伏笔、图谱变化、时间轴
 *
 * 仅保留前端仍在直调的单源端点；tab 级聚合 mock 见 ./tabs.ts。
 */
import { http, HttpResponse, delay } from "msw";
import {
  createCharacters,
  createEmotionTrendWindows,
  createForeshadowingThreads,
  createDiagnosis,
  createGraphChangesPage,
  createEventTimeline,
  taskDb,
} from "../data";

const BASE = import.meta.env.VITE_API_BASE_URL || "";
// 2026-08-14 D3：新管线只写 completed，aggregated/diagnosed 为旧合同状态（与后端 READABLE_RUN_STATUSES 对齐）
const READABLE_TASK_STATUSES = new Set(["completed"]);

/** 检查任务是否已进入可读终态；未完成时模拟真实后端的 AnalysisNotCompleteError */
async function checkTaskReady(novelId: string, taskId: string): Promise<Response | null> {
  const tasks = taskDb.get(novelId) ?? [];
  const task = tasks.find((t) => t.task_id === taskId);

  if (!task) {
    return HttpResponse.json({ detail: "任务不存在" }, { status: 404 });
  }
  if (!READABLE_TASK_STATUSES.has(task.status)) {
    return HttpResponse.json(
      {
        detail: `分析未完成，当前状态: ${task.status}`,
        error_type: "AnalysisNotCompleteError",
        status_code: 400,
        run_status: task.status,
      },
      { status: 400 }
    );
  }
  return null;
}

// 获取 /api/novels/:novelId/characters（角色排行/角色表 tab 数据源）
export const charactersHandler = http.get(
  `${BASE}/api/novels/:novelId/characters`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(300);
    return HttpResponse.json(createCharacters());
  }
);

// 获取 /api/novels/:novelId/emotion-trend（情绪趋势 tab 数据源，支持 position range）
export const emotionTrendHandler = http.get(
  `${BASE}/api/novels/:novelId/emotion-trend`,
  async ({ request, params }) => {
    const { novelId } = params;
    const url = new URL(request.url);
    const taskId = url.searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    const windowParagraphs = Number(url.searchParams.get("window_paragraphs")) || 20;
    const rawRange = url.searchParams.get("range");
    const rangeParts = rawRange?.split(",").map(Number);
    const range =
      rangeParts && rangeParts.length === 2 && rangeParts.every(Number.isFinite)
        ? ([rangeParts[0], rangeParts[1]] as [number, number])
        : null;
    await delay(400);
    return HttpResponse.json(createEmotionTrendWindows(windowParagraphs, range));
  },
);

// 获取 /api/novels/:novelId/diagnosis（诊断摘要/价值与主题 tab 数据源）
export const diagnosisHandler = http.get(
  `${BASE}/api/novels/:novelId/diagnosis`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(500);
    return HttpResponse.json(createDiagnosis());
  }
);

// 获取 /api/novels/:novelId/foreshadowing-threads（Setup 台账 tab 数据源）
export const foreshadowingThreadsHandler = http.get(
  `${BASE}/api/novels/:novelId/foreshadowing-threads`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(250);
    return HttpResponse.json(createForeshadowingThreads());
  }
);

// 获取 /api/novels/:novelId/graph/changes（图谱变化 tab 数据源）
export const graphChangesHandler = http.get(
  `${BASE}/api/novels/:novelId/graph/changes`,
  async ({ request, params }) => {
    const { novelId } = params;
    const url = new URL(request.url);
    const taskId = url.searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(200);
    // 2026-08-13 P2 防御：limit 为 0/非数字时钳制到 1，避免空页死循环
    // （createGraphChangesPage 的 next_cursor 与入参相同会无限翻页）
    const limit = Math.max(1, Number(url.searchParams.get("changes_limit")) || 8);
    return HttpResponse.json(
      createGraphChangesPage(
        url.searchParams.get("changes_cursor"),
        limit
      )
    );
  }
);

// 获取 /api/novels/:novelId/timeline（2026-08-20 事件森林一树一节点）
export const timelineHandler = http.get(
  `${BASE}/api/novels/:novelId/timeline`,
  async ({ request, params }) => {
    const { novelId } = params;
    const url = new URL(request.url);
    const taskId = url.searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(400);
    const data = createEventTimeline();
    data.meta.novel_id = novelId as string;
    return HttpResponse.json(data);
  }
);

// 主题全量分布 mock（赛道 D）：4 主题 × 60 段，权重和为 1
const MOCK_NUM_TOPICS = 4;
const MOCK_SERIES_POINTS = Array.from({ length: 60 }, (_, index) => {
  const base = index / 60;
  const raw = [0.4 * Math.cos(base * Math.PI) + 0.3, 0.25 + 0.2 * Math.sin(base * 2 * Math.PI), 0.18, 0.12].map(
    (value) => Math.max(0.02, value)
  );
  const total = raw.reduce((sum, value) => sum + value, 0);
  return {
    paragraph_id: index,
    chapter_id: Math.floor(index / 15) + 1,
    chapter_sequence: Math.floor(index / 15) + 1,
    start_position: index * 960,
    token_count: 240,
    weights: raw.map((value) => Number((value / total).toFixed(6))),
  };
});

// 获取 /api/novels/:novelId/topics/series（主题演进 tab 数据源）
export const topicSeriesHandler = http.get(
  `${BASE}/api/novels/:novelId/topics/series`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(400);
    return HttpResponse.json({
      run_id: taskId,
      model: {
        model_key: "gensim-lda",
        library_version: "4.4.0",
        pipeline_version: "1.0",
        num_topics: MOCK_NUM_TOPICS,
        artifact_key: "models/topic/mock-run",
        artifact_sha256: "a".repeat(64),
      },
      num_topics: MOCK_NUM_TOPICS,
      points: MOCK_SERIES_POINTS,
      unavailable_reason: null,
    });
  }
);

// 获取 /api/novels/:novelId/topics/shifts（主题迁移 tab 数据源）
export const topicShiftsHandler = http.get(
  `${BASE}/api/novels/:novelId/topics/shifts`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(300);
    return HttpResponse.json({
      candidates: [
        { position: 14400, paragraph_start: 14, paragraph_end: 19, score: 0.6123, window_token_total: 1440 },
        { position: 28800, paragraph_start: 29, paragraph_end: 34, score: 0.4811, window_token_total: 1440 },
        { position: 43200, paragraph_start: 44, paragraph_end: 49, score: 0.3564, window_token_total: 1440 },
      ],
      config: { window_size: 6, min_tokens_per_window: 800, score_threshold: 0.3, max_candidates: 20 },
      unavailable_reason: null,
    });
  }
);

// 获取 /api/novels/:novelId/topics/emotion（主题情绪 tab 数据源）
export const topicEmotionHandler = http.get(
  `${BASE}/api/novels/:novelId/topics/emotion`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(300);
    return HttpResponse.json({
      run_id: taskId,
      model: {
        model_key: "gensim-lda",
        library_version: "4.4.0",
        pipeline_version: "1.0",
        num_topics: MOCK_NUM_TOPICS,
        artifact_key: "models/topic/mock-run",
        artifact_sha256: "a".repeat(64),
      },
      emotion: [
        { topic_id: 0, emotion: 0.2136, weighted_token_total: 9820.5 },
        { topic_id: 1, emotion: -0.1421, weighted_token_total: 8410.2 },
        { topic_id: 2, emotion: 0.0384, weighted_token_total: 6120.8 },
        { topic_id: 3, emotion: null, weighted_token_total: null },
      ],
      unavailable_reason: null,
    });
  }
);
