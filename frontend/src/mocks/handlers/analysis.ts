/**
 * MSW Handler — 分析任务：创建、继续、状态、重新分析、删除
 *
 * createTask / reanalyze 创建新任务并以定时器模拟进度推进；resumeTask 复用同一 task_id；
 * taskStatus 返回由模拟计时器更新的当前进度；任务完成后所有结果 API 返回数据
 */
import { http, HttpResponse, delay } from "msw";
import { taskDb, createTask } from "../data";
import type { TaskStatus } from "@/api/types";

const BASE = import.meta.env.VITE_API_BASE_URL || "";

/* ------------------------------------------------------------------ */
/*  模拟进度状态（内存）                                                 */
/* ------------------------------------------------------------------ */

interface SimulatedTask { novelId: string; taskId: string; status: TaskStatus; timer: ReturnType<typeof setTimeout> | null; }

const simulatedTasks = new Map<string, SimulatedTask>();

function updateTaskRecord(novelId: string, taskId: string, updates: {status: TaskStatus}) {
  const task = (taskDb.get(novelId) ?? []).find((item) => item.task_id === taskId);
  if (task) task.status = updates.status;
}

function startSimulation(novelId: string, taskId: string) {
  const sim: SimulatedTask = {novelId, taskId, status: "running", timer: null};
  simulatedTasks.set(taskId, sim);
  updateTaskRecord(novelId, taskId, {status: "running"});
  sim.timer = setTimeout(() => {
    sim.status = "completed";
    updateTaskRecord(novelId, taskId, {status: "completed"});
    sim.timer = null;
  }, 18000);
}

function createAndStartTask(novelId: string) {
  const taskId = Math.random().toString(36).slice(2,10);
  const tasks = taskDb.get(novelId) ?? [];
  tasks.unshift(createTask(novelId,"pending",{task_id:taskId}));
  taskDb.set(novelId,tasks);
  startSimulation(novelId,taskId);
  return taskId;
}

export const createTaskHandler = http.post(`${BASE}/api/novels/:novelId/tasks`, async ({ params }) => {
  await delay(500);
  const { novelId } = params;
  const taskId = createAndStartTask(novelId as string);

  return HttpResponse.json({
    novel_id: novelId,
    task_id: taskId,
    message: "分析任务已创建并启动",
  });
});

export const reanalyzeHandler = http.post(`${BASE}/api/novels/:novelId/reanalyze`, async ({ params }) => {
  await delay(500);
  const { novelId } = params;
  const taskId = createAndStartTask(novelId as string);

  return HttpResponse.json({
    novel_id: novelId,
    task_id: taskId,
    message: "重新分析任务已创建",
  });
});

function buildTaskStatusPayload(novelId: string, taskId: string) {
  const task = (taskDb.get(novelId) ?? []).find((item) => item.task_id === taskId);
  const status = simulatedTasks.get(taskId)?.status ?? task?.status;
  return status ? HttpResponse.json({novel_id: novelId, task_id: taskId, status})
    : HttpResponse.json({detail: "任务不存在"}, {status: 404});
}

export const taskStatusHandler = http.get(
  `${BASE}/api/novels/:novelId/tasks/:taskId/status`,
  async ({ params }) => {
    await delay(100);
    const { novelId, taskId } = params;
    return buildTaskStatusPayload(novelId as string, taskId as string);
  }
);

export const resumeTaskHandler = http.post(
  `${BASE}/api/novels/:novelId/tasks/:taskId/resume`,
  async ({ params }) => {
    await delay(300);
    const { novelId, taskId } = params;
    const tasks = taskDb.get(novelId as string) ?? [];
    const task = tasks.find((item) => item.task_id === taskId);

    if (!task) {
      return HttpResponse.json({ detail: "任务不存在" }, { status: 404 });
    }

    // resume 允许 cancelled（与真实后端 analysis_service 一致）
    if (!["pending", "failed", "cancelled"].includes(task.status)) {
      return HttpResponse.json(
        { detail: `仅支持继续 pending/failed/cancelled 任务，当前状态为 ${task.status}` },
        { status: 400 }
      );
    }

    const existingSim = simulatedTasks.get(taskId as string);
    if (existingSim) {
      if (existingSim.timer && ["pending", "running", "cancelling"].includes(existingSim.status)) {
        return HttpResponse.json(
          { detail: `仅支持继续 pending/failed 任务，当前状态为 ${existingSim.status}` },
          { status: 400 }
        );
      }
      if (existingSim.timer) {
        clearInterval(existingSim.timer);
      }
      simulatedTasks.delete(taskId as string);
    }

    task.status = "pending";
    startSimulation(novelId as string, taskId as string);

    return HttpResponse.json({
      novel_id: novelId,
      task_id: taskId,
      message: "分析任务已继续执行",
    });
  }
);

export const batchDeleteTasksHandler = http.post(
  `${BASE}/api/novels/:novelId/tasks/batch-delete`,
  async ({ request, params }) => {
    await delay(300);
    const { novelId } = params;
    const body = (await request.json()) as { task_ids: string[] };
    const tasks = taskDb.get(novelId as string) ?? [];
    const deleted: string[] = [];
    const failed: Array<{ task_id: string; reason: string }> = [];

    for (const tid of body.task_ids) {
      const idx = tasks.findIndex((t) => t.task_id === tid);
      if (idx !== -1) {
        tasks.splice(idx, 1);
        const sim = simulatedTasks.get(tid);
        if (sim?.timer) {
          clearInterval(sim.timer);
          simulatedTasks.delete(tid);
        }
        deleted.push(tid);
      } else {
        failed.push({ task_id: tid, reason: "任务不存在" });
      }
    }

    return HttpResponse.json({
      success: failed.length === 0,
      message: failed.length === 0
        ? `成功删除 ${deleted.length} 个任务`
        : `部分删除成功: ${deleted.length} 个成功, ${failed.length} 个失败`,
      deleted_count: deleted.length,
      failed_count: failed.length,
      deleted_ids: deleted,
      failed_ids: failed,
    });
  }
);

export const analysisTasksHandler = http.get(`${BASE}/api/novels/:novelId/tasks`, async ({ params }) => {
  await delay(200);
  const { novelId } = params;
  const tasks = taskDb.get(novelId as string) ?? [];

  return HttpResponse.json({
    novel_id: novelId,
    tasks: tasks.map((t) => ({
      task_id: t.task_id,
      novel_id: t.novel_id,
      status: t.status,
    })),
  });
});

export const deleteTaskHandler = http.delete(
  `${BASE}/api/novels/:novelId/tasks/:taskId`,
  async ({ params }) => {
    await delay(200);
    const { novelId, taskId } = params;
    const tasks = taskDb.get(novelId as string) ?? [];
    const idx = tasks.findIndex((t) => t.task_id === taskId);
    if (idx !== -1) tasks.splice(idx, 1);

    const sim = simulatedTasks.get(taskId as string);
    if (sim?.timer) {
      clearInterval(sim.timer);
      simulatedTasks.delete(taskId as string);
    }

    return new HttpResponse(null, { status: 204 });
  }
);

export const cancelTaskHandler = http.post(
  `${BASE}/api/novels/:novelId/tasks/:taskId/cancel`,
  async ({ params }) => {
    await delay(200);
    const { novelId, taskId } = params;

    const tasks = taskDb.get(novelId as string) ?? [];
    const task = tasks.find((t) => t.task_id === taskId);

    if (!task) {
      return HttpResponse.json({ detail: "任务不存在" }, { status: 404 });
    }

    if (task.status === "completed") {
      return HttpResponse.json({ detail: "任务已完成，无需取消" }, { status: 400 });
    }

    if (task.status === "cancelled" || task.status === "cancelling") {
      return HttpResponse.json({ detail: `任务已${task.status === "cancelling" ? "在取消中" : "取消"}` }, { status: 400 });
    }

    const sim = simulatedTasks.get(taskId as string);
    if (sim?.timer) {
      clearInterval(sim.timer);
      sim.timer = null;
      simulatedTasks.delete(taskId as string);
    }

    task.status = "cancelled";

    return HttpResponse.json({
      task_id: taskId,
      status: "cancelled",
      message: "任务已取消",
    });
  }
);
