/**
 * Mock 数据工厂函数
 *
 * 生成与后端 API 类型一致的假数据，用于 MSW handler
 * 任何 mock 中修改此处即可影响全局返回数据
 */
import type {
  Novel,
  AnalysisTask,
  Character,
  ParagraphCurvePoint,
  EmotionTrendWindow,
  ChapterMetricsResponse,
  Topic,
  DiagnosisResult,
  ForeshadowingThread,
  GraphData,
  GraphChange,
  GraphChangesPageInfo,
  GraphChangesPageResponse,
  TimelineCompositeNode,
  TimelineNode,
  TimelineResponse,
  NarrativeStructureMetrics,
  EmotionStatsMetrics,
  CharacterStatsMetrics,
  StyleStatsMetrics,
  GlobalStats,
} from "@/api/types";

/* ------------------------------------------------------------------ */
/*  辅助函数                                                           */
/* ------------------------------------------------------------------ */

function uuid(): string {
  return crypto.randomUUID?.() ?? Math.random().toString(36).slice(2);
}

function dateAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

function encodeGraphChangesCursor(offset: number): string {
  return btoa(JSON.stringify({ offset })).replace(/=+$/u, "");
}

function decodeGraphChangesCursor(cursor?: string | null): number {
  if (!cursor) return 0;
  const normalized = cursor.padEnd(Math.ceil(cursor.length / 4) * 4, "=");
  const payload = JSON.parse(atob(normalized)) as { offset?: unknown };
  return typeof payload.offset === "number" && payload.offset >= 0 ? payload.offset : 0;
}

function buildGraphChangesPageInfo(total: number, start: number, limit: number): GraphChangesPageInfo {
  const end = Math.min(start + limit, total);
  return {
    limit,
    returned_count: end - start,
    total,
    has_more: end < total,
    next_cursor: end < total ? encodeGraphChangesCursor(end) : null,
  };
}

const MOCK_TIMELINE_TOTAL_CHUNKS = 120;

const MOCK_GRAPH_CHARACTERS = [
  { entity_id: 1, name: "萧炎", role: "protagonist", first_seen_chapter: 1, last_seen_chapter: 118 },
  { entity_id: 2, name: "药老", role: "main", first_seen_chapter: 4, last_seen_chapter: 115 },
  { entity_id: 3, name: "纳兰嫣然", role: "main", first_seen_chapter: 9, last_seen_chapter: 100 },
  { entity_id: 4, name: "美杜莎", role: "supporting", first_seen_chapter: 28, last_seen_chapter: 110 },
  { entity_id: 5, name: "云韵", role: "supporting", first_seen_chapter: 40, last_seen_chapter: 95 },
  { entity_id: 6, name: "小医仙", role: "supporting", first_seen_chapter: 48, last_seen_chapter: 108 },
  { entity_id: 7, name: "薰儿", role: "main", first_seen_chapter: 15, last_seen_chapter: 120 },
  { entity_id: 8, name: "海波东", role: "supporting", first_seen_chapter: 36, last_seen_chapter: 112 },
] as const;

const MOCK_GRAPH_RELATION_CHANGES = [
  {
    change_id: "relation:101:fact-12:1",
    chapter_id: 12,
    from_entity_id: 1,
    to_entity_id: 2,
    from_name: "萧炎",
    to_name: "药老",
    relation_type: "师徒",
    relation_change_kind: "assert",
    confidence: 0.96,
    source_relation_row_id: 1001,
    directionality: "directed",
  },
  {
    change_id: "relation:102:fact-24:1",
    chapter_id: 24,
    from_entity_id: 1,
    to_entity_id: 3,
    from_name: "萧炎",
    to_name: "纳兰嫣然",
    relation_type: "敌对",
    relation_change_kind: "reinforce",
    confidence: 0.87,
    source_relation_row_id: 1002,
    directionality: "directed",
  },
  {
    change_id: "relation:103:fact-39:1",
    chapter_id: 39,
    from_entity_id: 1,
    to_entity_id: 8,
    from_name: "萧炎",
    to_name: "海波东",
    relation_type: "盟友",
    relation_change_kind: "assert",
    confidence: 0.82,
    source_relation_row_id: 1003,
    directionality: "directed",
  },
  {
    change_id: "relation:104:fact-56:1",
    chapter_id: 56,
    from_entity_id: 1,
    to_entity_id: 4,
    from_name: "萧炎",
    to_name: "美杜莎",
    relation_type: "盟友",
    relation_change_kind: "reinforce",
    confidence: 0.73,
    source_relation_row_id: 1004,
    directionality: "directed",
  },
  {
    change_id: "relation:105:fact-72:1",
    chapter_id: 72,
    from_entity_id: 1,
    to_entity_id: 7,
    from_name: "萧炎",
    to_name: "薰儿",
    relation_type: "爱慕",
    relation_change_kind: "reinforce",
    confidence: 0.9,
    source_relation_row_id: 1005,
    directionality: "directed",
  },
  {
    change_id: "relation:106:fact-90:1",
    chapter_id: 90,
    from_entity_id: 1,
    to_entity_id: 5,
    from_name: "萧炎",
    to_name: "云韵",
    relation_type: "盟友",
    relation_change_kind: "weaken",
    confidence: 0.61,
    source_relation_row_id: 1006,
    directionality: "directed",
  },
  {
    change_id: "relation:107:fact-104:1",
    chapter_id: 104,
    from_entity_id: 1,
    to_entity_id: 6,
    from_name: "萧炎",
    to_name: "小医仙",
    relation_type: "盟友",
    relation_change_kind: "reinforce",
    confidence: 0.66,
    source_relation_row_id: 1007,
    directionality: "directed",
  },
  {
    change_id: "relation:108:fact-116:1",
    chapter_id: 116,
    from_entity_id: 1,
    to_entity_id: 3,
    from_name: "萧炎",
    to_name: "纳兰嫣然",
    relation_type: "敌对",
    relation_change_kind: "break",
    confidence: 0.78,
    source_relation_row_id: 1008,
    directionality: "directed",
  },
];

/* ------------------------------------------------------------------ */
/*  小说                                                               */
/* ------------------------------------------------------------------ */

const NOVEL_TITLES = [
  { title: "斗破苍穹", author: "天蚕土豆", filename: "斗破苍穹.txt", size: 4_567_890 },
  { title: "凡人修仙传", author: "忘语", filename: "凡人修仙传.txt", size: 8_234_567 },
  { title: "遮天", author: "辰东", filename: "遮天.txt", size: 6_123_456 },
  { title: "完美世界", author: "辰东", filename: "完美世界.txt", size: 5_987_654 },
  { title: "诡秘之主", author: "爱潜水的乌贼", filename: "诡秘之主.txt", size: 7_345_678 },
];

export function createNovel(overrides?: Partial<Novel>): Novel {
  const sample = NOVEL_TITLES[Math.floor(Math.random() * NOVEL_TITLES.length)];
  return {
    novel_id: uuid(),
    title: sample.title,
    filename: sample.filename,
    author: sample.author,
    upload_time: dateAgo(Math.floor(Math.random() * 30)),
    file_size: sample.size,
    ...overrides,
  };
}

export function createNovels(count = 8): Novel[] {
  return Array.from({ length: count }, (_, i) => createNovel({ ...NOVEL_TITLES[i % NOVEL_TITLES.length] }));
}

/** 内存小说存储（模拟数据库） */
export const novelDb = new Map<string, Novel>();
export const novelList: Novel[] = createNovels(5);
novelList.forEach((n) => novelDb.set(n.novel_id, n));

/* ------------------------------------------------------------------ */
/*  分析任务                                                           */
/* ------------------------------------------------------------------ */

export function createTask(
  novelId: string,
  status: AnalysisTask["status"] = "completed",
  overrides?: Partial<AnalysisTask>
): AnalysisTask {
  const completed = status === "completed";
  return {
    task_id: uuid(),
    novel_id: novelId,
    status,
    created_at: dateAgo(1),
    completed_at: completed ? dateAgo(0) : undefined,
    error: status === "failed" ? "模拟分析失败" : undefined,
    ...overrides,
  };
}

/** 内存任务存储 */
export const taskDb = new Map<string, AnalysisTask[]>();

// 为已有小说预创建一些已完成任务
novelList.forEach((novel) => {
  const tasks = [
    createTask(novel.novel_id, "completed"),
  ];
  taskDb.set(novel.novel_id, tasks);
});

/* ------------------------------------------------------------------ */
/*  角色                                                               */
/* ------------------------------------------------------------------ */

const NAMES = ["萧炎", "药老", "纳兰嫣然", "美杜莎", "林修崖", "海波东", "云韵", "小医仙", "薰儿", "韩立"];
const ROLE_FUNCTIONS = ["protagonist", "antagonist", "mentor", "love_interest", "supporting"];

export function createCharacters(count = 15): Character[] {
  return NAMES.slice(0, count).map((name, i) => ({
    name,
    appearance_count: Math.floor(Math.random() * 500 + 50),
    dominant_role_function: ROLE_FUNCTIONS[i % ROLE_FUNCTIONS.length],
    role_function_distribution: Object.fromEntries(
      ROLE_FUNCTIONS.map((rf) => [rf, Math.random()])
    ) as Record<string, number>,
    dominant_role_ratio: +(Math.random() * 0.6 + 0.3).toFixed(2),
    narrative_focus_score: i === 0 ? 0.95 : +(Math.random() * 0.5).toFixed(2),
    is_focus_character: i < 2,
    avg_emotion_score: +(Math.random() * 2 - 0.5).toFixed(2),
  }));
}

/* ------------------------------------------------------------------ */
/*  情绪曲线（M4：段落粒度，x 坐标统一为 0-1 position 值域）           */
/* ------------------------------------------------------------------ */

// 每章段数（与 createParagraphCurves 的 chapter 切分保持一致）
const MOCK_PARAGRAPHS_PER_CHAPTER = 40;

export function createParagraphCurves(count = 300): ParagraphCurvePoint[] {
  return Array.from({ length: count }, (_, i) => {
    const t = count > 1 ? i / (count - 1) : 0;
    // 模拟: 开头平稳、中段波动上升、结尾回落
    const base = 0.3 + 0.3 * Math.sin(t * Math.PI) + 0.15 * Math.sin(t * 6 * Math.PI);
    const pos = base + (Math.random() - 0.4) * 0.15;
    const neg = 0.2 - base * 0.3 + (Math.random() - 0.5) * 0.1;
    const net = pos - neg;
    const surface = 0.2 + 0.5 * Math.abs(Math.sin(t * 4 * Math.PI)) + Math.random() * 0.1;
    const charCount = 40 + Math.floor(Math.random() * 41);
    return {
      paragraph_id: i + 1,
      chapter_id: Math.floor(i / MOCK_PARAGRAPHS_PER_CHAPTER) + 1,
      paragraph_index: i % MOCK_PARAGRAPHS_PER_CHAPTER,
      global_start_char: i * 60,
      global_end_char: i * 60 + charCount,
      position: +t.toFixed(4),
      char_count: charCount,
      token_count: Math.round(charCount / 1.6),
      pos_density: +pos.toFixed(4),
      neg_density: +Math.max(0, neg).toFixed(4),
      net_density: +net.toFixed(4),
      smoothed_net_density: +(net * 0.7 + pos * 0.3).toFixed(4),
      surface_tension: +Math.min(1, surface).toFixed(4),
      smoothed_surface_tension: +(Math.min(1, surface * 0.8 + 0.1)).toFixed(4),
    };
  });
}

/** 2026-08-15 生成窗口情绪趋势 mock 数据以覆盖窗口粒度与缩放请求 */
export function createEmotionTrendWindows(
  windowParagraphs = 20,
  range: [number, number] | null = null,
): EmotionTrendWindow[] {
  const totalParagraphs = 300;
  const size = Math.max(5, Math.min(40, Math.trunc(windowParagraphs)));
  const startParagraph = Math.max(0, Math.floor((range?.[0] ?? 0) * totalParagraphs));
  const endParagraph = Math.min(
    totalParagraphs - 1,
    Math.ceil((range?.[1] ?? 1) * totalParagraphs) - 1,
  );
  if (startParagraph > endParagraph) return [];

  const windows: EmotionTrendWindow[] = [];
  for (let paragraphStart = startParagraph; paragraphStart <= endParagraph; paragraphStart += size) {
    const paragraphEnd = Math.min(paragraphStart + size - 1, endParagraph);
    const positionStart = paragraphStart / totalParagraphs;
    const positionEnd = (paragraphEnd + 1) / totalParagraphs;
    const progress = (positionStart + positionEnd) / 2;
    const posCoverage = +(0.35 + 0.25 * Math.sin(progress * Math.PI)).toFixed(4);
    const negCoverage = +(0.2 + 0.12 * Math.cos(progress * Math.PI)).toFixed(4);
    const pooledPos = +(posCoverage / 20).toFixed(4);
    const pooledNeg = +(negCoverage / 20).toFixed(4);
    windows.push({
      window_index: windows.length,
      position: progress,
      start_position: positionStart,
      end_position: positionEnd,
      paragraph_start: paragraphStart,
      paragraph_end: paragraphEnd,
      chapter_start: Math.floor(paragraphStart / MOCK_PARAGRAPHS_PER_CHAPTER) + 1,
      chapter_end: Math.floor(paragraphEnd / MOCK_PARAGRAPHS_PER_CHAPTER) + 1,
      pos_coverage: posCoverage,
      neg_coverage: negCoverage,
      pooled_pos_density: pooledPos,
      pooled_neg_density: pooledNeg,
      pooled_net_density: +(pooledPos - pooledNeg).toFixed(4),
      smoothed_pos_coverage: posCoverage,
      smoothed_neg_coverage: negCoverage,
      smoothed_pooled_pos_density: pooledPos,
      smoothed_pooled_neg_density: pooledNeg,
      smoothed_pooled_net_density: +(pooledPos - pooledNeg).toFixed(4),
      token_total: (paragraphEnd - paragraphStart + 1) * 25,
      hit_paragraphs: Math.round((paragraphEnd - paragraphStart + 1) * posCoverage),
      paragraph_total: paragraphEnd - paragraphStart + 1,
    });
  }
  return windows;
}

/* ------------------------------------------------------------------ */
/*  章节指标汇总（M4）                                                 */
/* ------------------------------------------------------------------ */

export function createChapterMetrics(): ChapterMetricsResponse {
  const totalParagraphs = 300;
  const totalChapters = Math.ceil(totalParagraphs / MOCK_PARAGRAPHS_PER_CHAPTER);
  const chapters = Array.from({ length: totalChapters }, (_, chapterIdx) => {
    const chapterId = chapterIdx + 1;
    const paragraphCount =
      chapterIdx === totalChapters - 1
        ? totalParagraphs - chapterIdx * MOCK_PARAGRAPHS_PER_CHAPTER
        : MOCK_PARAGRAPHS_PER_CHAPTER;
    const totalChars = paragraphCount * 60;
    const progress = chapterId / totalChapters;
    const base = 0.3 + 0.3 * Math.sin(progress * Math.PI) + 0.15 * Math.sin(progress * 6 * Math.PI);
    const narrativeFunctions = ["引入", "发展", "高潮", "收束"] as const;
    return {
      chapter_id: chapterId,
      paragraph_count: paragraphCount,
      total_chars: totalChars,
      total_tokens: Math.round(totalChars / 1.6),
      pos_density: +(base + 0.05).toFixed(4),
      neg_density: +Math.max(0, 0.2 - base * 0.3).toFixed(4),
      net_density: +(base * 0.7).toFixed(4),
      fight_density: +(0.05 + 0.1 * Math.abs(Math.sin(progress * 3 * Math.PI))).toFixed(4),
      exclaim_per_100_chars: +(2 + Math.random() * 4).toFixed(2),
      question_per_100_chars: +(1 + Math.random() * 3).toFixed(2),
      pause_per_100_chars: +(1.5 + Math.random() * 2).toFixed(2),
      dialogue_ratio: +(0.3 + Math.random() * 0.3).toFixed(3),
      avg_sent_len: +(16 + Math.random() * 8).toFixed(2),
      sent_len_std: +(5 + Math.random() * 4).toFixed(2),
      ttr: +(0.5 + Math.random() * 0.25).toFixed(3),
      mtld: +(45 + Math.random() * 30).toFixed(2),
      narrative_function: narrativeFunctions[chapterIdx % narrativeFunctions.length] ?? null,
      pivot_moment: chapterIdx === 2 || chapterIdx === 5,
      cliffhanger: chapterIdx === 3 || chapterIdx === 6,
      emotional_valence: base > 0.5 ? "积极" : base < 0.25 ? "消极" : "中性",
    };
  });
  return {
    chapters,
    book: {
      total_chapters: totalChapters,
      total_paragraphs: totalParagraphs,
      total_chars: 300 * 60,
      total_tokens: Math.round((300 * 60) / 1.6),
      pos_density: 0.52,
      neg_density: 0.31,
      net_density: 0.21,
      fight_density: 0.12,
      exclaim_per_100_chars: 3.2,
      question_per_100_chars: 2.1,
      pause_per_100_chars: 2.4,
      dialogue_ratio: 0.45,
      avg_sent_len: 18.5,
      sent_len_std: 7.1,
      ttr: 0.62,
      mtld: 58.4,
      chapter_narrative_function_share: {
        引入: 0.15,
        发展: 0.55,
        高潮: 0.2,
        收束: 0.1,
      },
      chapter_pivot_rate: 0.25,
      chapter_cliffhanger_rate: 0.25,
      chapter_emotional_valence_share: {
        积极: 0.4,
        中性: 0.35,
        消极: 0.25,
      },
    },
  };
}

/* ------------------------------------------------------------------ */
/*  主题                                                               */
/* ------------------------------------------------------------------ */

const TOPIC_WORD_BANK = [
  ["修炼", "突破", "灵力", "境界", "丹田", "斗气", "功法", "经脉"],
  ["战斗", "敌人", "招式", "武器", "防御", "进攻", "力量", "杀"],
  ["情感", "爱情", "思念", "牵挂", "温柔", "承诺", "守护", "心"],
  ["阴谋", "算计", "势力", "家族", "权力", "争斗", "谋略", "利益"],
  ["冒险", "探索", "秘境", "宝藏", "未知", "危险", "机遇", "奇迹"],
  ["成长", "蜕变", "历练", "磨难", "坚韧", "信念", "意志", "觉醒"],
  ["友情", "兄弟", "信任", "义气", "并肩", "承诺", "陪伴", "牺牲"],
  ["命运", "天意", "轮回", "因果", "宿命", "抉择", "转机", "重生"],
];

export function createTopics(count = 8): Topic[] {
  return Array.from({ length: count }, (_, i) => ({
    topic_id: i + 1,
    words: TOPIC_WORD_BANK[i % TOPIC_WORD_BANK.length],
    weight: +(0.05 + Math.random() * 0.15).toFixed(3),
    label: undefined,
  }));
}

/* ------------------------------------------------------------------ */
/*  诊断结果                                                           */
/* ------------------------------------------------------------------ */

export function createDiagnosis(): DiagnosisResult {
  const foreshadowExpectation = +(Math.random() * 0.3 + 0.5).toFixed(2);
  return {
    genre_labels: ["仙侠"],
    style_labels: ["热血", "史诗", "爽文"],
    foreshadow_expectation: foreshadowExpectation,
    focus_structure: "dual",
    focus_characters: ["萧炎", "药老"],
    narrative_arc_type: "三幕式 + 多重高潮",
    arc_scores: {
      萧炎: Number((Math.random() * 2 + 7).toFixed(1)),
      药老: Number((Math.random() * 2 + 6).toFixed(1)),
      纳兰嫣然: Number((Math.random() * 2 + 5).toFixed(1)),
      美杜莎: Number((Math.random() * 2 + 5).toFixed(1)),
    },
    diagnosis:
      "本作品采用双主角并行成长结构，萧炎承担行动与突破线，药老承担传承与命运牵引线。故事节奏把握得当，情节层层递进，伏笔铺垫自然。师徒互动与共同成长持续推动叙事升级，在传统修仙框架中形成更鲜明的双焦点张力。",
    value_logic_type: "混合型",
    value_logic_reason: "萧炎与药老通过共同历险、传承与自我突破，体现了互相成就的成长逻辑。",
    power_stance_score: 4,
    power_stance_reason: "作品展现了对权力与力量的辩证思考，既有对强者的敬畏，也有对弱者尊严的关怀。",
    common_people_dignity: 4,
    dignity_reason: "通过多个配角视角，展现了普通人在强权世界中的尊严与价值。",
    cultural_depth_score: 4,
    cultural_depth_reason: "融合了道家思想、中医理论等传统文化元素，文化底蕴较深。",
    topic_labels: ["修炼成长", "热血战斗", "情感纠葛", "势力博弈", "秘境探索", "友情义气"],
    core_cast: ["萧炎", "药老", "纳兰嫣然", "美杜莎", "小医仙", "薰儿"],
    main_characters: ["萧炎", "药老", "纳兰嫣然", "美杜莎"],
    theme_color: "#6366F1",
  };
}

export function createForeshadowingThreads(): ForeshadowingThread[] {
  return [
    {
      setup_id: "setup-thread-1",
      first_chapter_id: 3,
      last_chapter_id: 12,
      anchor_chapter_ids: [3, 7, 12],
      setup_summary: "主角在旧山门发现一枚残缺令牌，后续多次被提及。",
      setup_kind: "伏笔",
      expected_payoff_family: "身份揭露",
      payoff_likelihood: "high",
      confidence: "high",
      strength: "high",
      status: "reinforced",
      active: true,
      latest_reason: "最新章节再次强调令牌与失踪长老有关。",
      latest_why_unresolved_now: "当前任务尚未给出令牌来历的明确揭晓。",
    },
  ];
}

/* ------------------------------------------------------------------ */
/*  知识图谱                                                           */
/* ------------------------------------------------------------------ */

export function createGraph(): GraphData {
  const nodes = MOCK_GRAPH_CHARACTERS.map((character) => ({
    entity_id: character.entity_id,
    name: character.name,
    entity_type: "character" as const,
    first_seen_chapter: character.first_seen_chapter,
    last_seen_chapter: character.last_seen_chapter,
    state_chapter_id: 12,
    state: {
      primary_role_function: character.role,
      status: "active",
    },
  }));

  const edges = [
    { source: 1, target: 2, relation_type: "师徒" },
    { source: 1, target: 3, relation_type: "敌对" },
    { source: 1, target: 4, relation_type: "盟友" },
    { source: 1, target: 5, relation_type: "盟友" },
    { source: 1, target: 6, relation_type: "盟友" },
    { source: 1, target: 7, relation_type: "爱慕" },
    { source: 2, target: 8, relation_type: "盟友" },
  ].map((edge, index) => ({
    relation_id: `relation-${index + 1}`,
    state_chapter_id: 12,
    source_entity_id: edge.source,
    target_entity_id: edge.target,
    source_name: nodes.find((node) => node.entity_id === edge.source)?.name ?? "未知实体",
    target_name: nodes.find((node) => node.entity_id === edge.target)?.name ?? "未知实体",
    relation_type: edge.relation_type,
    directionality: "bidirectional" as const,
    relation_semantics: "ordinary" as const,
    attributes: {},
    is_active: true,
    changes: [],
  }));

  return {
    chapter_id: 12,
    chapter_order: 12,
    first_chapter_id: 111,
    last_chapter_id: 120,
    nodes,
    edges,
  };
}

export function createGraphChangesPage(cursor?: string | null, limit = 8): GraphChangesPageResponse {
  const graph = createGraph();
  const allChanges: GraphChange[] = MOCK_GRAPH_RELATION_CHANGES.map((change) => ({
    change_id: change.change_id,
    change_kind: "relation",
    chapter_id: graph.chapter_id,
    chapter_order: graph.chapter_order,
    fact_id: `fact:${change.change_id}`,
    effective_chapter_id: change.chapter_id,
    changes: [{ change_kind: change.relation_change_kind }],
    relation_id: `relation:${change.source_relation_row_id ?? change.change_id}`,
    from_entity_id: change.from_entity_id,
    to_entity_id: change.to_entity_id,
    from_name: graph.nodes.find((node) => node.entity_id === change.from_entity_id)?.name ?? change.from_name,
    to_name: graph.nodes.find((node) => node.entity_id === change.to_entity_id)?.name ?? change.to_name,
    relation_type: change.relation_type,
    relation_change_kind: change.relation_change_kind,
    directionality: change.directionality === "directed" ? "directed" : "bidirectional",
    relation_semantics: "ordinary",
  }));
  const start = decodeGraphChangesCursor(cursor);
  const pageInfo = buildGraphChangesPageInfo(allChanges.length, start, limit);
  return {
    changes: allChanges.slice(start, start + limit),
    page_info: pageInfo,
  };
}

/* ------------------------------------------------------------------ */
/*  叙事时间轴                                                         */
/* ------------------------------------------------------------------ */

const PHASE_EVENTS = [
  "少年初入修炼之路",
  "首次突破斗者境界",
  "遭遇家族危机",
  "结识药老，开启修炼新篇",
  "进入迦南学院",
  "与纳兰嫣然的三 年之约",
  "炼药师大赛夺冠",
  "发现异火踪迹",
  "深入险地，生死搏杀",
  "实力飞跃，突破大斗师",
  "四方势力齐聚云岚宗",
  "最终决战，称霸大陆",
];

const CHAR_SETS: string[][] = [
  ["萧炎", "药老"],
  ["萧炎"],
  ["萧炎", "纳兰嫣然"],
  ["萧炎", "药老"],
  ["萧炎", "美杜莎", "林修崖"],
  ["萧炎", "纳兰嫣然", "薰儿"],
  ["萧炎", "药老", "海波东"],
  ["萧炎"],
  ["萧炎", "美杜莎", "小医仙"],
  ["萧炎", "药老"],
  ["萧炎", "云韵", "美杜莎", "海波东"],
  ["萧炎", "药老", "薰儿", "美杜莎"],
];

function resolveTimelinePhaseName(chapterId: number): "引入期" | "发展期" | "高潮期" | "收束期" {
  if (chapterId <= 30) return "引入期";
  if (chapterId <= 75) return "发展期";
  if (chapterId <= 105) return "高潮期";
  return "收束期";
}

export function createTimeline(): TimelineResponse {
  const plotNodes: TimelineNode[] = PHASE_EVENTS.map((event, i) => ({
    node_id: `plot:${Math.floor((i / PHASE_EVENTS.length) * 120 + 5)}`,
    anchor_chapter_id: Math.floor((i / PHASE_EVENTS.length) * MOCK_TIMELINE_TOTAL_CHUNKS + 5),
    progress: +(i / PHASE_EVENTS.length).toFixed(3),
    importance_score: +(0.3 + Math.random() * 0.7).toFixed(2),
    level: (Math.random() > 0.6 ? 1 : Math.random() > 0.3 ? 2 : 3) as 1 | 2 | 3,
    summary: event,
    characters: CHAR_SETS[i],
      phase_name: (["引入期", "发展期", "高潮期", "收束期"] as const)[Math.min(Math.floor(i / 3), 3)],
    node_type: "plot" as const,
    node_subtype: "plot" as const,
    score_breakdown: {
      pivot: i === 0 || i === 5 || i === PHASE_EVENTS.length - 1 ? 3 : 0,
      cliffhanger: i === 4 || i === 7 ? 2 : 0,
      tension: +(Math.random() * 2).toFixed(2),
    },
    plot_flags: {
      is_pivot: i === 0 || i === 5 || i === PHASE_EVENTS.length - 1,
      is_cliffhanger: i === 4 || i === 7,
      tension_percentile: Math.floor(Math.random() * 100),
    },
  }));

  const relationNodes: TimelineNode[] = createGraphChangesPage(null, MOCK_GRAPH_RELATION_CHANGES.length).changes.map((change) => ({
    node_id: change.change_id,
    anchor_chapter_id: change.effective_chapter_id,
    progress: +(change.effective_chapter_id / MOCK_TIMELINE_TOTAL_CHUNKS).toFixed(3),
    importance_score:
      change.relation_change_kind === "break" || change.relation_change_kind === "assert"
        ? 0.88
        : change.relation_change_kind === "reinforce"
          ? 0.74
          : 0.63,
    level: change.relation_change_kind === "break" || change.relation_change_kind === "assert" ? 1 : 2,
    summary: `${change.from_name}与${change.to_name}关系变化`,
    characters: [change.from_name ?? "未知实体", change.to_name ?? "未知实体"],
    phase_name: resolveTimelinePhaseName(change.effective_chapter_id),
    node_type: "relation" as const,
    node_subtype: (change.relation_change_kind ?? "refine") as TimelineNode["node_subtype"],
    score_breakdown: {
      change_type_weight:
        change.relation_change_kind === "break" ? 2.6 : change.relation_change_kind === "assert" ? 2.4 : change.relation_change_kind === "reinforce" ? 1.8 : 1.6,
      pair_importance: 0.8,
    },
    graph_changes: [
      {
        change_id: change.change_id,
        change_kind: "relation",
        chapter_id: change.chapter_id,
        fact_id: change.fact_id,
        effective_chapter_id: change.effective_chapter_id,
        changes: change.changes,
        relation_id: change.relation_id,
        from_char: change.from_name,
        to_char: change.to_name,
        relation_type: change.relation_type,
        relation_change_kind: change.relation_change_kind,
        directionality: change.directionality,
      },
    ],
  }));

  const stateNodes: TimelineNode[] = MOCK_GRAPH_CHARACTERS.slice(0, 2).map((character, index) => {
    const anchorChapterId = index === 0 ? 18 : 42;
    return {
      node_id: `state:${character.entity_id}:${anchorChapterId}`,
      anchor_chapter_id: anchorChapterId,
      progress: +(anchorChapterId / MOCK_TIMELINE_TOTAL_CHUNKS).toFixed(3),
      importance_score: index === 0 ? 0.76 : 0.62,
      level: index === 0 ? 1 : 2,
      summary: `${character.name}状态更新`,
      characters: [character.name],
      phase_name: resolveTimelinePhaseName(anchorChapterId),
      node_type: "state" as const,
      node_subtype: "state" as const,
      score_breakdown: { state_change_weight: index === 0 ? 2.2 : 1.5 },
      graph_changes: [
        {
          change_id: `state:${character.entity_id}:${anchorChapterId}`,
          change_kind: "state" as const,
          chapter_id: 12,
          fact_id: `state-fact:${character.entity_id}:${anchorChapterId}`,
          effective_chapter_id: anchorChapterId,
          changes: [{ field: "status", value: index === 0 ? "突破" : "收徒" }],
          entity_id: character.entity_id,
          entity_name: character.name,
        },
      ],
    };
  });

  const lifecycleNodes: TimelineNode[] = MOCK_GRAPH_CHARACTERS.flatMap((character) => [
    {
      node_id: `lifecycle:entry:${character.entity_id}:${character.first_seen_chapter}`,
      anchor_chapter_id: character.first_seen_chapter,
      progress: +(character.first_seen_chapter / MOCK_TIMELINE_TOTAL_CHUNKS).toFixed(3),
      importance_score: character.role === "protagonist" ? 0.82 : 0.58,
      level: (character.role === "protagonist" ? 1 : 2) as 1 | 2,
      summary: `${character.name}首次登场`,
      characters: [character.name],
      phase_name: resolveTimelinePhaseName(character.first_seen_chapter),
      node_type: "lifecycle" as const,
      node_subtype: "entry" as const,
      score_breakdown: { character_importance: character.role === "protagonist" ? 2.4 : 1.4, entry_exit_bonus: 1.4 },
      lifecycle_events: [{ entity_id: Number(character.entity_id), character_name: character.name, lifecycle_type: "entry" as const }],
    },
    {
      node_id: `lifecycle:exit:${character.entity_id}:${character.last_seen_chapter}`,
      anchor_chapter_id: character.last_seen_chapter,
      progress: +(character.last_seen_chapter / MOCK_TIMELINE_TOTAL_CHUNKS).toFixed(3),
      importance_score: character.role === "protagonist" ? 0.76 : 0.54,
      level: (character.role === "protagonist" ? 1 : 2) as 1 | 2,
      summary: `${character.name}最后活跃`,
      characters: [character.name],
      phase_name: resolveTimelinePhaseName(character.last_seen_chapter),
      node_type: "lifecycle" as const,
      node_subtype: "exit" as const,
      score_breakdown: { character_importance: character.role === "protagonist" ? 2.4 : 1.4, entry_exit_bonus: 1.2 },
      lifecycle_events: [{ entity_id: Number(character.entity_id), character_name: character.name, lifecycle_type: "exit" as const }],
    },
  ]);

  const nodes: TimelineNode[] = [...plotNodes, ...stateNodes, ...relationNodes, ...lifecycleNodes].sort((a, b) => a.progress - b.progress);

  const tension_curve = Array.from({ length: MOCK_TIMELINE_TOTAL_CHUNKS }, (_, i) => {
    const t = i / MOCK_TIMELINE_TOTAL_CHUNKS;
    return +(0.3 + 0.4 * Math.sin(t * Math.PI) + 0.2 * Math.sin(t * 8 * Math.PI) + Math.random() * 0.05).toFixed(3);
  });

  return {
    meta: {
      novel_id: "",
      novel_name: "斗破苍穹",
      total_chapters: MOCK_TIMELINE_TOTAL_CHUNKS,
    },
    phases: [
      { name: "引入期", start: 0, end: 30, ratio: 0.25 },
      { name: "发展期", start: 30, end: 75, ratio: 0.375 },
      { name: "高潮期", start: 75, end: 105, ratio: 0.25 },
      { name: "收束期", start: 105, end: 120, ratio: 0.125 },
    ],
    composite_nodes: nodes.map((node, index): TimelineCompositeNode => ({
      node_id: `composite:${node.node_type}:${node.anchor_chapter_id}:${index}`,
      anchor_chapter_id: node.anchor_chapter_id,
      start_chapter_id: node.anchor_chapter_id,
      end_chapter_id: node.anchor_chapter_id,
      progress: node.progress,
      start_progress: node.progress,
      end_progress: node.progress,
      importance_score: node.importance_score,
      level: node.level,
      summary: node.summary,
      characters: node.characters,
      phase_name: node.phase_name,
      node_type: node.node_type,
      node_subtypes: [node.node_subtype],
      representative_node_id: node.node_id,
      child_node_ids: [node.node_id],
    })),
    atomic_nodes: nodes,
    tension_curve,
    phase_basis: "tension",
  };
}

/* ------------------------------------------------------------------ */
/*  指标                                                               */
/* ------------------------------------------------------------------ */

export function createNarrativeStructure(): NarrativeStructureMetrics {
  return {
    act1_ratio: 0.25,
    act2_ratio: 0.45,
    act3_ratio: 0.30,
    climax_spacing: 0.35,
    middle_collapse_index: 0.2,
    chapter_narrative_function_share: {
      "引入期": 0.15,
      "发展期": 0.55,
      "高潮期": 0.85,
      "收束期": 0.3,
    },
    cliffhanger_rate: 0.12,
    climax_count: 4,
    // M4：climax_positions 与曲线 position 同域（0-1 比例），直接作为高潮 markPoint 的 x 坐标
    climax_positions: [0.25, 0.45, 0.65, 0.8],
    climax_heights: [0.7, 0.85, 0.92, 0.88],
    peak_escalation: "递进式",
    dominant_climax_pos: 0.65,
  };
}

export function createEmotionStats(): EmotionStatsMetrics {
  return {
    lexical_pos_neg_ratio: 1.65,
    arc_delta: 0.42,
    positive_ratio: 0.52,
    negative_ratio: 0.31,
    neutral_ratio: 0.17,
    recovery_speed: 0.73,
    chapter_pivot_rate: 0.15,
    lexical_emotion_trend: "前低后高",
  };
}

export function createCharacterStats(): CharacterStatsMetrics {
  return {
    network_density: 0.34,
    greimas_coverage: 0.85,
    function_coverage_distribution: {
      主体: 0.32,
      客体: 0.18,
      发送者: 0.12,
    },
    antagonist_strength_gap: 0.27,
    relation_change_per_10k_chars: 0.14,
    degree_centrality: {
      萧炎: 0.62,
      药老: 0.51,
      纳兰嫣然: 0.37,
    },
  };
}

export function createStyleStats(): StyleStatsMetrics {
  return {
    string_token_diversity: 0.72,
    avg_sent_len: 18.5,
    dialogue_ratio: 0.45,
  };
}

/**
 * 2026-08-16 创建全书统计 mock
 * 返回详情概览波动卡使用的情绪与节奏全书聚合字段
 */
export function createGlobalStats(): GlobalStats {
  return {
    total_chapters: MOCK_TIMELINE_TOTAL_CHUNKS,
    total_chars: 36000,
    avg_mtld: 58.4,
    avg_ttr: 0.62,
    avg_sent_len: 18.5,
    emotion_std: 0.18,
    emotion_max: 0.48,
    emotion_min: -0.22,
    rhythm_avg: 0.61,
    rhythm_std: 0.14,
    rhythm_max: 0.92,
    rhythm_min: 0.22,
  };
}
