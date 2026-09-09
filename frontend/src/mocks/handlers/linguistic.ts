/**
 * MSW Handler — 语言特征端点（词法句法 / 词向量 tab 数据源）
 */
import { http, HttpResponse, delay } from "msw";
import { taskDb } from "../data";

const BASE = import.meta.env.VITE_API_BASE_URL || "";
const READABLE_TASK_STATUSES = new Set(["completed"]);

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

const POS_RATIOS = { noun: 0.32, verb: 0.21, adj: 0.12, adv: 0.08, pron: 0.09, prep: 0.06, other: 0.12 };
const PATTERNS = { short: 0.42, medium: 0.31, long: 0.18, compound: 0.07, parallel_candidate: 0.02 };
const WORD_LENGTHS = { 1: 0.18, 2: 0.46, 3: 0.19, 4: 0.12, "5_plus": 0.05 };
const RELATIONS = { HED: 0.18, SBV: 0.24, VOB: 0.22, ATT: 0.21, CMP: 0.08, POB: 0.07 };

function buildGroupStats(scale = 1) {
  return {
    token_total: Math.round(24000 * scale),
    sentence_total: Math.round(1600 * scale),
    word_length_ratios: WORD_LENGTHS,
    pos_ratios: POS_RATIOS,
    sentence_pattern_ratios: PATTERNS,
    avg_dependency_depth: 2.84,
    max_dependency_depth: 9,
    dependency_relation_ratios: RELATIONS,
    dependency_root_count: Math.round(1600 * scale),
    boundary_pos_score_sum: Math.round(14.27 * scale * 100) / 100,
    boundary_neg_score_sum: Math.round(2447.93 * scale * 100) / 100,
  };
}

// GET /api/novels/:novelId/linguistic/features
export const linguisticFeaturesHandler = http.get(
  `${BASE}/api/novels/:novelId/linguistic/features`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(300);
    return HttpResponse.json({
      run_id: taskId,
      paragraph_count: 420,
      ...buildGroupStats(3),
      chapters: [1, 2, 3, 4].map((chapterId) => ({
        chapter_id: chapterId,
        ...buildGroupStats(0.75),
      })),
      unavailable_reason: null,
    });
  }
);

// GET /api/novels/:novelId/linguistic/word2vec
export const linguisticWord2vecHandler = http.get(
  `${BASE}/api/novels/:novelId/linguistic/word2vec`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(300);
    // 三组二维正交/对角质心 → 相似度矩阵确定可算
    const centroids = [
      { pos_group: "noun", weighted_token_total: 7680, embedding_vector: [1, 0] },
      { pos_group: "verb", weighted_token_total: 5040, embedding_vector: [0, 1] },
      { pos_group: "adj", weighted_token_total: 2880, embedding_vector: [0.7071, 0.7071] },
    ];
    const matrix = centroids.map((a) =>
      centroids.map((b) => {
        const dot = a.embedding_vector.reduce((sum, value, index) => sum + value * b.embedding_vector[index], 0);
        return Number(dot.toFixed(6));
      })
    );
    return HttpResponse.json({
      run_id: taskId,
      model: { embedding_dimension: 2, vocabulary_size: 48210, artifact_scope: "pretrained_finetuned" },
      pos_coverage: [
        { pos_group: "noun", source_token_total: 7680, in_vocabulary_token_total: 7104, coverage_ratio: 0.925 },
        { pos_group: "verb", source_token_total: 5040, in_vocabulary_token_total: 4420, coverage_ratio: 0.8769 },
        { pos_group: "adj", source_token_total: 2880, in_vocabulary_token_total: 2210, coverage_ratio: 0.7674 },
        { pos_group: "pron", source_token_total: 2160, in_vocabulary_token_total: 2100, coverage_ratio: 0.9722 },
      ],
      pos_centroids: centroids,
      pos_similarity_matrix: matrix,
      unavailable_reason: null,
    });
  }
);
