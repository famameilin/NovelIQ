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
  ChunkCurvePoint,
  Topic,
  DiagnosisResult,
  ForeshadowingThread,
  GraphData,
  GraphEvent,
  GraphEventsPageInfo,
  GraphEventsPageResponse,
  TimelineCompositeNode,
  TimelineNode,
  TimelineResponse,
  NarrativeStructureMetrics,
  EmotionStatsMetrics,
  CharacterStatsMetrics,
  StyleStatsMetrics,
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

function encodeGraphEventsCursor(offset: number): string {
  return btoa(JSON.stringify({ offset })).replace(/=+$/u, "");
}

function decodeGraphEventsCursor(cursor?: string | null): number {
  if (!cursor) return 0;
  const normalized = cursor.padEnd(Math.ceil(cursor.length / 4) * 4, "=");
  const payload = JSON.parse(atob(normalized)) as { offset?: unknown };
  return typeof payload.offset === "number" && payload.offset >= 0 ? payload.offset : 0;
}

function buildGraphEventsPageInfo(total: number, start: number, limit: number): GraphEventsPageInfo {
  const end = Math.min(start + limit, total);
  return {
    limit,
    returned_count: end - start,
    total,
    has_more: end < total,
    next_cursor: end < total ? encodeGraphEventsCursor(end) : null,
  };
}

const MOCK_TIMELINE_TOTAL_CHUNKS = 120;

const MOCK_GRAPH_CHARACTERS = [
  { entity_id: "1", name: "萧炎", role: "protagonist", first_seen_chunk: 1, last_seen_chunk: 118 },
  { entity_id: "2", name: "药老", role: "main", first_seen_chunk: 4, last_seen_chunk: 115 },
  { entity_id: "3", name: "纳兰嫣然", role: "main", first_seen_chunk: 9, last_seen_chunk: 100 },
  { entity_id: "4", name: "美杜莎", role: "supporting", first_seen_chunk: 28, last_seen_chunk: 110 },
  { entity_id: "5", name: "云韵", role: "supporting", first_seen_chunk: 40, last_seen_chunk: 95 },
  { entity_id: "6", name: "小医仙", role: "supporting", first_seen_chunk: 48, last_seen_chunk: 108 },
  { entity_id: "7", name: "薰儿", role: "main", first_seen_chunk: 15, last_seen_chunk: 120 },
  { entity_id: "8", name: "海波东", role: "supporting", first_seen_chunk: 36, last_seen_chunk: 112 },
] as const;

const MOCK_GRAPH_RELATION_EVENTS: GraphEvent[] = [
  {
    relation_event_id: 101,
    chunk_id: 12,
    from_entity_id: 1,
    to_entity_id: 2,
    from_name: "萧炎",
    to_name: "药老",
    relation_type: "师徒",
    change_type: "新建",
    evidence: "药老正式收萧炎为徒。",
    confidence: 0.96,
    source_relation_row_id: 1001,
    directionality: "directed",
  },
  {
    relation_event_id: 102,
    chunk_id: 24,
    from_entity_id: 1,
    to_entity_id: 3,
    from_name: "萧炎",
    to_name: "纳兰嫣然",
    relation_type: "对手",
    change_type: "强化",
    evidence: "三年之约进一步升级双方对立。",
    confidence: 0.87,
    source_relation_row_id: 1002,
    directionality: "directed",
  },
  {
    relation_event_id: 103,
    chunk_id: 39,
    from_entity_id: 1,
    to_entity_id: 8,
    from_name: "萧炎",
    to_name: "海波东",
    relation_type: "盟友",
    change_type: "新建",
    evidence: "海波东决定与萧炎合作。",
    confidence: 0.82,
    source_relation_row_id: 1003,
    directionality: "directed",
  },
  {
    relation_event_id: 104,
    chunk_id: 56,
    from_entity_id: 1,
    to_entity_id: 4,
    from_name: "萧炎",
    to_name: "美杜莎",
    relation_type: "盟友",
    change_type: "强化",
    evidence: "险境中二人关系更加稳固。",
    confidence: 0.73,
    source_relation_row_id: 1004,
    directionality: "directed",
  },
  {
    relation_event_id: 105,
    chunk_id: 72,
    from_entity_id: 1,
    to_entity_id: 7,
    from_name: "萧炎",
    to_name: "薰儿",
    relation_type: "恋人",
    change_type: "强化",
    evidence: "重逢后彼此情感被再次确认。",
    confidence: 0.9,
    source_relation_row_id: 1005,
    directionality: "directed",
  },
  {
    relation_event_id: 106,
    chunk_id: 90,
    from_entity_id: 1,
    to_entity_id: 5,
    from_name: "萧炎",
    to_name: "云韵",
    relation_type: "盟友",
    change_type: "弱化",
    evidence: "局势变化导致两人的合作松动。",
    confidence: 0.61,
    source_relation_row_id: 1006,
    directionality: "directed",
  },
  {
    relation_event_id: 107,
    chunk_id: 104,
    from_entity_id: 1,
    to_entity_id: 6,
    from_name: "萧炎",
    to_name: "小医仙",
    relation_type: "盟友",
    change_type: "强化",
    evidence: "共同经历险境后互信提升。",
    confidence: 0.66,
    source_relation_row_id: 1007,
    directionality: "directed",
  },
  {
    relation_event_id: 108,
    chunk_id: 116,
    from_entity_id: 1,
    to_entity_id: 3,
    from_name: "萧炎",
    to_name: "纳兰嫣然",
    relation_type: "对手",
    change_type: "断裂",
    evidence: "恩怨在终局被彻底切断。",
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
/*  情绪曲线                                                           */
/* ------------------------------------------------------------------ */

export function createChunkCurves(count = 120): ChunkCurvePoint[] {
  return Array.from({ length: count }, (_, i) => {
    const t = i / count;
    // 模拟: 开头平稳、中段波动上升、结尾回落
    const base = 0.3 + 0.3 * Math.sin(t * Math.PI) + 0.15 * Math.sin(t * 6 * Math.PI);
    const pos = base + (Math.random() - 0.4) * 0.15;
    const neg = 0.2 - base * 0.3 + (Math.random() - 0.5) * 0.1;
    return {
      chunk_id: i + 1,
      pos_density: +pos.toFixed(4),
      neg_density: +Math.max(0, neg).toFixed(4),
      net_density: +(pos - neg).toFixed(4),
      smoothed_density: +(pos * 0.7 + neg * 0.3).toFixed(4),
      tension_proxy: +(0.2 + 0.5 * Math.abs(Math.sin(t * 4 * Math.PI)) + Math.random() * 0.1).toFixed(4),
      tension_composite: +(0.3 + 0.4 * Math.sin(t * 3 * Math.PI) + Math.random() * 0.1).toFixed(4),
    };
  });
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
      first_chunk_id: 3,
      last_chunk_id: 12,
      anchor_chunk_ids: [3, 7, 12],
      setup_summary: "主角在旧山门发现一枚残缺令牌，后续多次被提及。",
      setup_kind: "伏笔",
      expected_payoff_family: "身份揭露",
      payoff_likelihood: "high",
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
    first_seen_chunk: character.first_seen_chunk,
    last_seen_chunk: character.last_seen_chunk,
    role: character.role,
    status: "active",
  }));

  const edges = [
    { source: "1", target: "2", relation_type: "师徒", weight: 0.95 },
    { source: "1", target: "3", relation_type: "对手", weight: 0.78 },
    { source: "1", target: "4", relation_type: "盟友", weight: 0.72 },
    { source: "1", target: "5", relation_type: "盟友", weight: 0.5 },
    { source: "1", target: "6", relation_type: "盟友", weight: 0.61 },
    { source: "1", target: "7", relation_type: "恋人", weight: 0.85 },
    { source: "2", target: "8", relation_type: "盟友", weight: 0.43 },
  ];
  const allEvents = MOCK_GRAPH_RELATION_EVENTS;
  const initialEventLimit = 8;
  const events = allEvents.slice(0, initialEventLimit);

  const summary = {
    node_count: nodes.length,
    edge_count: edges.length,
    density: +(edges.length / (nodes.length * (nodes.length - 1))).toFixed(4),
    core_characters: nodes.slice(0, 5).map((node) => node.name),
    key_relations: edges.slice(0, 5).map((edge) => ({
      from: nodes.find((node) => node.entity_id === edge.source)?.name ?? "未知角色",
      to: nodes.find((node) => node.entity_id === edge.target)?.name ?? "未知角色",
      type: edge.relation_type,
      support_count: Math.max(1, Math.round((edge.weight ?? 0.4) * 10)),
    })),
  };

  const quality = {
    // Mock 合同遵循 authority 语义：`conflict_count` 只反映当前已确认关系
    conflict_count: 0,
    low_confidence_count: allEvents.filter((event) => (event.confidence ?? 0) < 0.6).length,
    conflicts: [],
    low_confidence_samples: allEvents
      .filter((event) => (event.confidence ?? 0) < 0.6)
      .slice(0, 5)
      .map((event) => ({
        relation_event_id: event.relation_event_id,
        chunk_id: event.chunk_id,
        from_name: event.from_name,
        to_name: event.to_name,
        relation_type: event.relation_type,
        change_type: event.change_type,
        confidence: event.confidence,
      })),
  };
  const events_page = buildGraphEventsPageInfo(allEvents.length, 0, initialEventLimit);

  return { nodes, edges, events, events_page, summary, quality };
}

export function createGraphEventsPage(cursor?: string | null, limit = 8): GraphEventsPageResponse {
  const graph = createGraph();
  const allEvents: GraphEvent[] = MOCK_GRAPH_RELATION_EVENTS.map((event) => ({
    ...event,
    from_name: graph.nodes.find((node) => Number(node.entity_id) === event.from_entity_id)?.name ?? event.from_name,
    to_name: graph.nodes.find((node) => Number(node.entity_id) === event.to_entity_id)?.name ?? event.to_name,
  }));
  const start = decodeGraphEventsCursor(cursor);
  const pageInfo = buildGraphEventsPageInfo(allEvents.length, start, limit);
  return {
    events: allEvents.slice(start, start + limit),
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

function resolveTimelinePhaseName(chunkId: number): "引入期" | "发展期" | "高潮期" | "收束期" {
  if (chunkId <= 30) return "引入期";
  if (chunkId <= 75) return "发展期";
  if (chunkId <= 105) return "高潮期";
  return "收束期";
}

export function createTimeline(): TimelineResponse {
  const plotNodes: TimelineNode[] = PHASE_EVENTS.map((event, i) => ({
    node_id: `plot:${Math.floor((i / PHASE_EVENTS.length) * 120 + 5)}`,
    anchor_chunk_id: Math.floor((i / PHASE_EVENTS.length) * MOCK_TIMELINE_TOTAL_CHUNKS + 5),
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

  const relationNodes: TimelineNode[] = MOCK_GRAPH_RELATION_EVENTS.map((event) => ({
    node_id: `relation:${event.relation_event_id}`,
    anchor_chunk_id: event.chunk_id,
    progress: +(event.chunk_id / MOCK_TIMELINE_TOTAL_CHUNKS).toFixed(3),
    importance_score:
      event.change_type === "断裂" || event.change_type === "新建"
        ? 0.88
        : event.change_type === "强化"
          ? 0.74
          : 0.63,
    level: event.change_type === "断裂" || event.change_type === "新建" ? 1 : 2,
    summary: `${event.from_name}与${event.to_name}${event.change_type}${event.relation_type}`,
    characters: [event.from_name, event.to_name],
    phase_name: resolveTimelinePhaseName(event.chunk_id),
    node_type: "relation" as const,
    node_subtype: event.change_type as "新建" | "强化" | "弱化" | "断裂",
    score_breakdown: {
      change_type_weight:
        event.change_type === "断裂" ? 2.6 : event.change_type === "新建" ? 2.4 : event.change_type === "强化" ? 1.8 : 1.6,
      pair_importance: +(event.confidence ?? 0.6).toFixed(2),
    },
    relation_events: [
      {
        relation_event_id: event.relation_event_id,
        from_char: event.from_name,
        to_char: event.to_name,
        relation_type: event.relation_type ?? "盟友",
        change_type: (event.change_type ?? "强化") as "新建" | "强化" | "弱化" | "断裂",
        evidence: event.evidence,
        confidence: event.confidence,
        directionality: event.directionality,
      },
    ],
  }));

  const lifecycleNodes: TimelineNode[] = MOCK_GRAPH_CHARACTERS.flatMap((character) => [
    {
      node_id: `lifecycle:entry:${character.entity_id}:${character.first_seen_chunk}`,
      anchor_chunk_id: character.first_seen_chunk,
      progress: +(character.first_seen_chunk / MOCK_TIMELINE_TOTAL_CHUNKS).toFixed(3),
      importance_score: character.role === "protagonist" ? 0.82 : 0.58,
      level: (character.role === "protagonist" ? 1 : 2) as 1 | 2,
      summary: `${character.name}首次登场`,
      characters: [character.name],
      phase_name: resolveTimelinePhaseName(character.first_seen_chunk),
      node_type: "lifecycle" as const,
      node_subtype: "entry" as const,
      score_breakdown: { character_importance: character.role === "protagonist" ? 2.4 : 1.4, entry_exit_bonus: 1.4 },
      lifecycle_events: [{ entity_id: Number(character.entity_id), character_name: character.name, lifecycle_type: "entry" as const }],
    },
    {
      node_id: `lifecycle:exit:${character.entity_id}:${character.last_seen_chunk}`,
      anchor_chunk_id: character.last_seen_chunk,
      progress: +(character.last_seen_chunk / MOCK_TIMELINE_TOTAL_CHUNKS).toFixed(3),
      importance_score: character.role === "protagonist" ? 0.76 : 0.54,
      level: (character.role === "protagonist" ? 1 : 2) as 1 | 2,
      summary: `${character.name}最后活跃`,
      characters: [character.name],
      phase_name: resolveTimelinePhaseName(character.last_seen_chunk),
      node_type: "lifecycle" as const,
      node_subtype: "exit" as const,
      score_breakdown: { character_importance: character.role === "protagonist" ? 2.4 : 1.4, entry_exit_bonus: 1.2 },
      lifecycle_events: [{ entity_id: Number(character.entity_id), character_name: character.name, lifecycle_type: "exit" as const }],
    },
  ]);

  const nodes: TimelineNode[] = [...plotNodes, ...relationNodes, ...lifecycleNodes].sort((a, b) => a.progress - b.progress);

  const tension_curve = Array.from({ length: MOCK_TIMELINE_TOTAL_CHUNKS }, (_, i) => {
    const t = i / MOCK_TIMELINE_TOTAL_CHUNKS;
    return +(0.3 + 0.4 * Math.sin(t * Math.PI) + 0.2 * Math.sin(t * 8 * Math.PI) + Math.random() * 0.05).toFixed(3);
  });

  return {
    meta: {
      novel_id: "",
      novel_name: "斗破苍穹",
      total_chunks: MOCK_TIMELINE_TOTAL_CHUNKS,
    },
    phases: [
      { name: "引入期", start: 0, end: 30, ratio: 0.25 },
      { name: "发展期", start: 30, end: 75, ratio: 0.375 },
      { name: "高潮期", start: 75, end: 105, ratio: 0.25 },
      { name: "收束期", start: 105, end: 120, ratio: 0.125 },
    ],
    composite_nodes: nodes.map((node, index): TimelineCompositeNode => ({
      node_id: `composite:${node.node_type}:${node.anchor_chunk_id}:${index}`,
      anchor_chunk_id: node.anchor_chunk_id,
      start_chunk_id: node.anchor_chunk_id,
      end_chunk_id: node.anchor_chunk_id,
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
    event_density: {
      "引入期": 0.15,
      "发展期": 0.55,
      "高潮期": 0.85,
      "收束期": 0.3,
    },
    cliffhanger_rate: 0.12,
    climax_count: 4,
    climax_positions: [30, 55, 78, 95],
    climax_heights: [0.7, 0.85, 0.92, 0.88],
    peak_escalation: "递进式",
    dominant_climax_pos: 0.65,
  };
}

export function createEmotionStats(): EmotionStatsMetrics {
  return {
    pos_neg_ratio: 1.65,
    positive_ratio: 0.52,
    negative_ratio: 0.31,
    neutral_ratio: 0.17,
    recovery_speed: 0.73,
    pivot_moment_density: 0.15,
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
    relation_change_freq: 0.14,
    degree_centrality: {
      萧炎: 0.62,
      药老: 0.51,
      纳兰嫣然: 0.37,
    },
  };
}

export function createStyleStats(): StyleStatsMetrics {
  return {
    vocab_breadth: 0.72,
    avg_sent_len: 18.5,
    dialogue_ratio: 0.45,
  };
}
