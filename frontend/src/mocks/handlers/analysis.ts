/**
 * MSW Handler — 分析任务：开始、重新分析、状态、任务列表、删除
 *
 * 关键设计：
 * - startAnalysis / reanalyze 会创建新任务，并以定时器模拟进度推进
 * - getAnalysisStatus 返回当前进度（由模拟计时器更新）
 * - 任务完成后所有结果 API 可正常返回数据
 *
 * 修改时间: 2026-04-07
 * 修改者: TraeAI
 * 任务: implement-task-cancellation
 * 修改内容: 添加模拟 LLM 输出，支持 HTTP 轮询显示
 */
import { http, HttpResponse, delay } from "msw";
import { taskDb, createTask } from "../data";
import type { TaskStatus } from "@/api/types";

const BASE = import.meta.env.VITE_API_BASE_URL || "";

/* ------------------------------------------------------------------ */
/*  模拟进度状态（内存）                                                 */
/* ------------------------------------------------------------------ */

interface SimulatedTask {
  novelId: string;
  taskId: string;
  status: TaskStatus;
  progress: number;
  currentStep: string;
  stage: string;
  subStage: string;
  current: number;
  total: number;
  startedAt: number;
  stageTimings: Record<string, number>;
  timer: ReturnType<typeof setInterval> | null;
  llmOutputs: string[];
}

const simulatedTasks = new Map<string, SimulatedTask>();

const STAGES = [
  { key: "preprocess", label: "预处理", weight: 0.08, steps: ["文本清洗", "分块处理"] },
  { key: "annotate", label: "标注分析", weight: 0.55, steps: ["角色识别", "对话抽取", "关系分析"] },
  { key: "aggregate", label: "数据聚合", weight: 0.15, steps: ["指标计算", "曲线生成"] },
  { key: "topic-model", label: "主题建模", weight: 0.1, steps: ["LDA训练", "主题提取"] },
  { key: "diagnose", label: "诊断报告", weight: 0.12, steps: ["综合诊断", "报告生成"] },
];

const TOTAL_ANALYSIS_MS = 18_000;

const MOCK_LLM_OUTPUTS = [
  "正在分析文本结构...",
  "识别到主角：张三，性格特征：勇敢、正直",
  "发现关键情节转折点：第15章 - 意外相遇",
  "分析对话模式：主角与反派的对峙场景",
  "提取情感曲线：高潮位于第28章",
  "主题建模完成，发现3个主要主题",
  "生成诊断报告...",
];

function startSimulation(novelId: string, taskId: string) {
  const sim: SimulatedTask = {
    novelId,
    taskId,
    status: "pending",
    progress: 0,
    currentStep: "等待开始",
    stage: "preprocess",
    subStage: "初始化",
    current: 0,
    total: 100,
    startedAt: Date.now(),
    stageTimings: {},
    timer: null,
    llmOutputs: [],
  };

  simulatedTasks.set(taskId, sim);

  sim.timer = setInterval(() => {
    const elapsed = Date.now() - sim.startedAt - 300;
    const progress = Math.min(100, (elapsed / TOTAL_ANALYSIS_MS) * 100);

    sim.progress = progress;

    if (progress >= 100) {
      sim.status = "completed";
      sim.currentStep = "分析完成";
      sim.stage = "completed";
      sim.progress = 100;

      const tasks = taskDb.get(novelId) ?? [];
      const task = tasks.find((t) => t.task_id === taskId);
      if (task) {
        task.status = "completed";
        task.completed_at = new Date().toISOString();
      }

      if (sim.timer) {
        clearInterval(sim.timer);
        sim.timer = null;
      }
      return;
    }

    let accumulated = 0;
    for (const stage of STAGES) {
      const stageEnd = (accumulated + stage.weight) * 100;
      if (progress < stageEnd) {
        sim.stage = stage.key;
        const stageProgress = (progress - accumulated * 100) / (stage.weight * 100);
        const stepIdx = Math.min(
          stage.steps.length - 1,
          Math.floor(stageProgress * stage.steps.length)
        );
        sim.subStage = stage.steps[stepIdx];
        sim.current = Math.floor(stageProgress * 100);
        sim.total = 100;
        sim.currentStep = `${stage.label} - ${stage.steps[stepIdx]}`;

        const statusMap: Record<string, TaskStatus> = {
          preprocess: "running",
          annotate: "running",
          aggregate: "running",
          "topic-model": "running",
          diagnose: "running",
        };
        sim.status = statusMap[stage.key] ?? "pending";

        if (Math.random() < 0.15 && sim.llmOutputs.length < MOCK_LLM_OUTPUTS.length) {
          const outputIdx = Math.floor(progress / 15);
          if (outputIdx < MOCK_LLM_OUTPUTS.length && !sim.llmOutputs.includes(MOCK_LLM_OUTPUTS[outputIdx])) {
            sim.llmOutputs.push(MOCK_LLM_OUTPUTS[outputIdx]);
          }
        }
        break;
      }
      accumulated += stage.weight;
    }
  }, 200);
}

export const analyzeHandler = http.post(`${BASE}/api/novels/:novelId/analyze`, async ({ params }) => {
  await delay(500);
  const { novelId } = params;
  const taskId = Math.random().toString(36).slice(2, 10);

  const task = createTask(novelId as string, "pending", {
    task_id: taskId,
  });

  const tasks = taskDb.get(novelId as string) ?? [];
  tasks.unshift(task);
  taskDb.set(novelId as string, tasks);

  startSimulation(novelId as string, taskId);

  return HttpResponse.json({
    novel_id: novelId,
    task_id: taskId,
    message: "分析任务已创建",
  });
});

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

export const reanalyzeHandler = http.post(`${BASE}/api/novels/:novelId/reanalyze`, async ({ params }) => {
  await delay(500);
  const { novelId } = params;
  const taskId = Math.random().toString(36).slice(2, 10);

  const task = createTask(novelId as string, "pending", {
    task_id: taskId,
  });

  const tasks = taskDb.get(novelId as string) ?? [];
  tasks.unshift(task);
  taskDb.set(novelId as string, tasks);

  startSimulation(novelId as string, taskId);

  return HttpResponse.json({
    novel_id: novelId,
    task_id: taskId,
    message: "重新分析任务已创建",
  });
});

export const analysisStatusHandler = http.get(
  `${BASE}/api/novels/:novelId/status`,
  async ({ params, request }) => {
    await delay(100);
    const { novelId } = params;
    const url = new URL(request.url);
    const taskId = url.searchParams.get("task_id");

    if (taskId) {
      const sim = simulatedTasks.get(taskId);
      if (sim) {
        return HttpResponse.json({
          novel_id: novelId,
          task_id: taskId,
          status: sim.status,
          progress: sim.progress,
          current_step: sim.currentStep,
          stage: sim.stage,
          sub_stage: sim.subStage,
          current: sim.current,
          total: sim.total,
          message: sim.currentStep,
          llm_outputs: sim.llmOutputs,
        });
      }

      const tasks = taskDb.get(novelId as string) ?? [];
      const task = tasks.find((t) => t.task_id === taskId);
      if (task) {
        return HttpResponse.json({
          novel_id: novelId,
          task_id: taskId,
          status: task.status,
          progress: task.status === "completed" ? 100 : 0,
          current_step: task.status === "completed" ? "分析完成" : "等待开始",
          stage: task.status,
        });
      }

      return HttpResponse.json(
        { detail: "任务不存在" },
        { status: 404 }
      );
    }

    const tasks = taskDb.get(novelId as string) ?? [];
    const runningTask = tasks.find((t) =>
      ["pending", "running", "cancelling"].includes(t.status)
    );

    if (runningTask) {
      const sim = simulatedTasks.get(runningTask.task_id);
      if (sim) {
        return HttpResponse.json({
          novel_id: novelId,
          task_id: sim.taskId,
          status: sim.status,
          progress: sim.progress,
          current_step: sim.currentStep,
          stage: sim.stage,
          sub_stage: sim.subStage,
          current: sim.current,
          total: sim.total,
          message: sim.currentStep,
          llm_outputs: sim.llmOutputs,
        });
      }
    }

    return HttpResponse.json({
      novel_id: novelId,
      status: "pending",
      progress: 0,
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
      created_at: t.created_at,
      completed_at: t.completed_at,
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
