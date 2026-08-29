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
  createTopics,
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

// 获取 /api/novels/:novelId/topics（主题词数据源）
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
