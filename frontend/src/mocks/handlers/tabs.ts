/**
 * MSW Handler — Tab 级聚合端点（/tabs/*）
 *
 * 组合既有 mock 数据工厂，保持与真实后端 tabs 响应相同的切片口径：
 * 指标类数据为聚合值，展示主体（图快照/诊断/伏笔线程）原样透传。
 */
import { http, HttpResponse, delay } from "msw";
import {
  createCharacters,
  createChapterMetrics,
  createDiagnosis,
  createEmotionStats,
  createEmotionTrendWindows,
  createGraph,
  createGraphChangesPage,
  createNarrativeStructure,
  createParagraphCurves,
  createCharacterStats,
  createStyleStats,
  createTopics,
  taskDb,
} from "../data";

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

function buildTopicModelMeta(numTopics: number) {
  return {
    model_key: "gensim-lda",
    library_version: "4.4.0",
    pipeline_version: "1.0",
    num_topics: numTopics,
    artifact_key: "models/topic/mock-run",
  };
}

// GET /api/novels/:novelId/tabs/dashboard
export const dashboardTabHandler = http.get(
  `${BASE}/api/novels/:novelId/tabs/dashboard`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(600);
    return HttpResponse.json({
      run_id: taskId,
      narrative_structure: createNarrativeStructure(),
      emotion_stats: createEmotionStats(),
      character_stats: createCharacterStats(),
      style_stats: createStyleStats(),
      chapter_metrics: createChapterMetrics(),
      topics: createTopics(),
      diagnosis: createDiagnosis(),
      emotion_trend: createEmotionTrendWindows(20, null),
    });
  }
);

// GET /api/novels/:novelId/tabs/rhythm
export const rhythmTabHandler = http.get(
  `${BASE}/api/novels/:novelId/tabs/rhythm`,
  async ({ request, params }) => {
    const { novelId } = params;
    const url = new URL(request.url);
    const taskId = url.searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(400);
    const maxPoints = Number(url.searchParams.get("max_points"));
    const count = Number.isFinite(maxPoints) && maxPoints > 0 ? Math.min(maxPoints, 5000) : 800;
    return HttpResponse.json({
      run_id: taskId,
      curves: createParagraphCurves(count),
      narrative_structure: createNarrativeStructure(),
    });
  }
);

// GET /api/novels/:novelId/tabs/character-function
export const characterFunctionTabHandler = http.get(
  `${BASE}/api/novels/:novelId/tabs/character-function`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(300);
    const diagnosis = createDiagnosis();
    return HttpResponse.json({
      run_id: taskId,
      characters: createCharacters(),
      focus_structure: diagnosis.focus_structure ?? null,
      focus_characters: diagnosis.focus_characters ?? null,
      arc_scores: diagnosis.arc_scores ?? null,
    });
  }
);

// GET /api/novels/:novelId/tabs/graph-network
export const graphNetworkTabHandler = http.get(
  `${BASE}/api/novels/:novelId/tabs/graph-network`,
  async ({ request, params }) => {
    const { novelId } = params;
    const url = new URL(request.url);
    const taskId = url.searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(400);
    const characters = createCharacters();
    const changeTotal = createGraphChangesPage(null, 1).page_info.total;
    return HttpResponse.json({
      run_id: taskId,
      snapshot: createGraph(),
      character_appearances: characters.map((character) => ({
        name: character.name,
        appearance_count: character.appearance_count,
      })),
      graph_metrics: {
        run_id: taskId,
        unavailable_reason: null,
        algorithm: { version: "graph-metrics-v1" },
        pagerank: Object.fromEntries(
          characters.slice(0, 8).map((character, index) => [character.name, Number((0.3 - index * 0.03).toFixed(6))])
        ),
        hits: { authority: {}, hub: {} },
        communities: { community_ids: {}, modularity: 0.42, interpretation: "structural_community_only" },
      },
      change_total: changeTotal,
      unavailable_reason: null,
    });
  }
);

// GET /api/novels/:novelId/tabs/topics-overview
export const topicsOverviewTabHandler = http.get(
  `${BASE}/api/novels/:novelId/tabs/topics-overview`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(400);
    const topics = createTopics();
    return HttpResponse.json({
      run_id: taskId,
      model: buildTopicModelMeta(topics.length),
      topics,
      distribution: topics.map((topic) => ({ topic_id: topic.topic_id, weight: topic.weight })),
      chapters: [1, 2, 3].map((chapterId) => ({
        chapter_id: chapterId,
        chapter_sequence: chapterId,
        chapter_title: `第${chapterId}章`,
        token_total: 1200,
        distribution: topics.map((topic, index) => ({
          topic_id: topic.topic_id,
          weight: Number(Math.max(0, topic.weight + (index % 2 === 0 ? 0.02 : -0.02) * chapterId).toFixed(6)),
        })),
      })),
      keywords: [
        { word: "宗门", score: 0.0812 },
        { word: "灵脉", score: 0.0643 },
        { word: "剑意", score: 0.0521 },
        { word: "长老", score: 0.0417 },
        { word: "秘境", score: 0.0388 },
      ],
      unavailable_reason: null,
      keyword_unavailable_reason: null,
    });
  }
);

// GET /api/novels/:novelId/tabs/linguistic-entities
export const linguisticEntitiesTabHandler = http.get(
  `${BASE}/api/novels/:novelId/tabs/linguistic-entities`,
  async ({ request, params }) => {
    const { novelId } = params;
    const taskId = new URL(request.url).searchParams.get("task_id") ?? "";
    const err = await checkTaskReady(novelId as string, taskId);
    if (err) return err;

    await delay(300);
    return HttpResponse.json({
      run_id: taskId,
      count_by_type: { person: 186, location: 74, organization: 31, item: 22 },
      surface_top: [
        { surface_text: "林渡", entity_type: "person", count: 92 },
        { surface_text: "顾霜", entity_type: "person", count: 61 },
        { surface_text: "萧遥", entity_type: "person", count: 33 },
        { surface_text: "青云宗", entity_type: "organization", count: 18 },
        { surface_text: "落霞谷", entity_type: "location", count: 11 },
      ],
      total_char_count: 186000,
      metric_hit_count: 47,
      fixed_phrase_density: 0.2527,
      four_char_candidate_count: 12,
      total_hits: 59,
      unavailable_reason: null,
    });
  }
);
