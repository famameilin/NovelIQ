/**
 * MSW Handler — 分析结果：角色、曲线、主题、诊断、图谱、时间轴、指标
 */
import { http, HttpResponse, delay } from "msw";
import {
  createCharacters,
  createChunkCurves,
  createForeshadowingThreads,
  createTopics,
  createDiagnosis,
  createGraph,
  createGraphEventsPage,
  createTimeline,
  createNarrativeStructure,
  createEmotionStats,
  createCharacterStats,
  createStyleStats,
  taskDb,
} from "../data";

const BASE = import.meta.env.VITE_API_BASE_URL || "";
const READABLE_TASK_STATUSES = new Set(["completed", "aggregated", "diagnosed"]);

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
      },
      { status: 400 }
    );
  }
  return null;
}

// GET /api/novels/:novelId/characters
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

// GET /api/novels/:novelId/chunk-curves
export const chunkCurvesHandler = http.get(
  `${BASE}/api/novels/:novelId/chunk-curves`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(400);
    return HttpResponse.json(createChunkCurves());
  }
);

// GET /api/novels/:novelId/topics
export const topicsHandler = http.get(
  `${BASE}/api/novels/:novelId/topics`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(300);
    return HttpResponse.json(createTopics());
  }
);

// GET /api/novels/:novelId/diagnosis
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

// GET /api/novels/:novelId/foreshadowing-threads
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

// GET /api/novels/:novelId/graph
export const graphHandler = http.get(
  `${BASE}/api/novels/:novelId/graph`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(400);
    return HttpResponse.json(createGraph());
  }
);

// GET /api/novels/:novelId/graph/events
export const graphEventsHandler = http.get(
  `${BASE}/api/novels/:novelId/graph/events`,
  async ({ request, params }) => {
    const { novelId } = params;
    const url = new URL(request.url);
    const taskId = url.searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(200);
    return HttpResponse.json(
      createGraphEventsPage(
        url.searchParams.get("events_cursor"),
        Number(url.searchParams.get("events_limit") ?? "8")
      )
    );
  }
);

// GET /api/novels/:novelId/timeline
export const timelineHandler = http.get(
  `${BASE}/api/novels/:novelId/timeline`,
  async ({ request, params }) => {
    const { novelId } = params;
    const url = new URL(request.url);
    const taskId = url.searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(400);
    const data = createTimeline();
    data.meta.novel_id = novelId as string;
    return HttpResponse.json(data);
  }
);

// GET /api/novels/:novelId/metrics/narrative-structure
export const narrativeStructureHandler = http.get(
  `${BASE}/api/novels/:novelId/metrics/narrative-structure`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(200);
    return HttpResponse.json(createNarrativeStructure());
  }
);

// GET /api/novels/:novelId/metrics/emotion-stats
export const emotionStatsHandler = http.get(
  `${BASE}/api/novels/:novelId/metrics/emotion-stats`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(200);
    return HttpResponse.json(createEmotionStats());
  }
);

// GET /api/novels/:novelId/metrics/character-stats
export const characterStatsHandler = http.get(
  `${BASE}/api/novels/:novelId/metrics/character-stats`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(200);
    return HttpResponse.json(createCharacterStats());
  }
);

// GET /api/novels/:novelId/metrics/style-stats
export const styleStatsHandler = http.get(
  `${BASE}/api/novels/:novelId/metrics/style-stats`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";

    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(200);
    return HttpResponse.json(createStyleStats());
  }
);
