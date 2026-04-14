/**
 * Mock 数据工厂函数
 *
 * 生成与后端 API 类型一致的假数据，用于 MSW handler。
 * 任何 mock 中修改此处即可影响全局返回数据。
 */
import type {
  Novel,
  AnalysisTask,
  Character,
  ChunkCurvePoint,
  Topic,
  DiagnosisResult,
  GraphData,
  TimelineResponse,
  NarrativeStructureMetrics,
  EmotionStatsMetrics,
  CharacterStatsMetrics,
  StyleStatsMetrics,
  CultureStatsMetrics,
} from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function uuid(): string {
  return crypto.randomUUID?.() ?? Math.random().toString(36).slice(2);
}

function dateAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

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
    protagonist_score: i === 0 ? 0.95 : +(Math.random() * 0.5).toFixed(2),
    is_protagonist: i === 0,
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
  return {
    narrative_type: "英雄之旅",
    foreshadow_rate: +(Math.random() * 0.3 + 0.5).toFixed(2),
    protagonist: "萧炎",
    narrative_arc_type: "三幕式 + 多重高潮",
    arc_scores: {
      introduction: +(Math.random() * 0.4 + 0.5).toFixed(2),
      development: +(Math.random() * 0.4 + 0.5).toFixed(2),
      climax: +(Math.random() * 0.3 + 0.6).toFixed(2),
      resolution: +(Math.random() * 0.4 + 0.5).toFixed(2),
    },
    diagnosis:
      "本作品采用经典英雄之旅叙事结构，主角从平凡少年成长为一代宗师。故事节奏把握得当，情节层层递进，伏笔铺垫自然。人物塑造丰满立体，情感线索贯穿始终。作品在传统修仙框架中融入了独特创新，世界观构建完整。建议在部分过渡段落可适当加快节奏，以保持读者的阅读兴趣。",
    value_logic_type: "自强不息",
    value_logic_reason: "主角通过不断修炼和突破自我，体现了自强不息的精神内核。",
    power_stance_score: +(Math.random() * 0.4 + 0.5).toFixed(2),
    power_stance_reason: "作品展现了对权力与力量的辩证思考，既有对强者的敬畏，也有对弱者尊严的关怀。",
    common_people_dignity: +(Math.random() * 0.3 + 0.5).toFixed(2),
    dignity_reason: "通过多个配角视角，展现了普通人在强权世界中的尊严与价值。",
    cultural_depth_score: +(Math.random() * 0.3 + 0.6).toFixed(2),
    cultural_depth_reason: "融合了道家思想、中医理论等传统文化元素，文化底蕴较深。",
    topic_labels: ["修炼成长", "热血战斗", "情感纠葛", "势力博弈", "秘境探索", "友情义气"],
    core_cast: ["萧炎", "药老", "纳兰嫣然", "美杜莎", "小医仙", "薰儿"],
    main_characters: ["萧炎", "药老", "纳兰嫣然", "美杜莎"],
    theme_color: "#6366F1",
  };
}

/* ------------------------------------------------------------------ */
/*  知识图谱                                                           */
/* ------------------------------------------------------------------ */

export function createGraph(): GraphData {
  const names = ["萧炎", "药老", "纳兰嫣然", "美杜莎", "云韵", "小医仙", "薰儿", "海波东", "林修崖", "韩立"];
  const types = ["character", "character", "character", "character", "character", "character", "character", "character", "character", "character"];

  const nodes = names.map((name, i) => ({
    entity_id: `char-${i}`,
    name,
    entity_type: types[i],
    first_seen_chunk: Math.floor(Math.random() * 10 + 1),
    last_seen_chunk: Math.floor(Math.random() * 100 + 50),
    role: i === 0 ? "protagonist" : i < 3 ? "main" : "supporting",
    status: i === 0 ? "active" : "active",
  }));

  const relationTypes = ["师徒", "恋人", "仇敌", "盟友", "朋友", "竞争", "合作"];
  const edges = [
    { source: "char-0", target: "char-1", relation_type: "师徒", weight: 0.95 },
    { source: "char-0", target: "char-2", relation_type: "恋人", weight: 0.7 },
    { source: "char-0", target: "char-3", relation_type: "盟友", weight: 0.6 },
    { source: "char-0", target: "char-4", relation_type: "朋友", weight: 0.5 },
    { source: "char-0", target: "char-5", relation_type: "合作", weight: 0.55 },
    { source: "char-0", target: "char-6", relation_type: "恋人", weight: 0.85 },
    { source: "char-1", target: "char-7", relation_type: "朋友", weight: 0.4 },
    { source: "char-2", target: "char-8", relation_type: "竞争", weight: 0.3 },
    { source: "char-3", target: "char-4", relation_type: "盟友", weight: 0.35 },
    { source: "char-5", target: "char-6", relation_type: "朋友", weight: 0.45 },
    { source: "char-7", target: "char-8", relation_type: "合作", weight: 0.25 },
    { source: "char-0", target: "char-9", relation_type: "朋友", weight: 0.5 },
  ];

  const changeTypes = ["新建", "强化", "弱化", "断裂"];

  const events = Array.from({ length: 8 }, (_, i) => ({
    relation_event_id: i + 1,
    chunk_id: Math.floor(Math.random() * 100 + 10),
    from_entity_id: i % 5,
    to_entity_id: (i + 1) % 5,
    from_name: names[i % 5],
    to_name: names[(i + 1) % 5],
    relation_type: relationTypes[i % relationTypes.length],
    change_type: changeTypes[i % changeTypes.length],
    evidence: `${names[i % 5]}与${names[(i + 1) % 5]}在关键桥段中产生新的互动。`,
    confidence: +(Math.random() * 0.5 + 0.4).toFixed(2),
    source_relation_row_id: i + 100,
    directionality: "bidirectional",
  }));

  const summary = {
    node_count: nodes.length,
    edge_count: edges.length,
    density: +(edges.length / (nodes.length * (nodes.length - 1))).toFixed(4),
    core_characters: names.slice(0, 5),
    key_relations: edges.slice(0, 5).map((edge) => ({
      from: names[Number(edge.source.replace("char-", ""))] ?? "未知角色",
      to: names[Number(edge.target.replace("char-", ""))] ?? "未知角色",
      type: edge.relation_type,
      support_count: Math.max(1, Math.round((edge.weight ?? 0.4) * 10)),
    })),
  };

  const quality = {
    // Mock contract follows authority semantics: conflict_count reflects current confirmed relations only.
    conflict_count: 0,
    low_confidence_count: events.filter((event) => (event.confidence ?? 0) < 0.6).length,
    conflicts: [],
    low_confidence_samples: events
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

  return { nodes, edges, events, summary, quality };
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

export function createTimeline(): TimelineResponse {
  const nodes = PHASE_EVENTS.map((event, i) => ({
    chunk_id: Math.floor((i / PHASE_EVENTS.length) * 120 + 5),
    progress: +(i / PHASE_EVENTS.length).toFixed(3),
    importance_score: +(0.3 + Math.random() * 0.7).toFixed(2),
    level: (Math.random() > 0.6 ? 1 : Math.random() > 0.3 ? 2 : 3) as 1 | 2 | 3,
    event,
    characters: CHAR_SETS[i],
    is_pivot: i === 0 || i === 5 || i === PHASE_EVENTS.length - 1,
    is_cliffhanger: i === 4 || i === 7,
    tension_percentile: Math.floor(Math.random() * 100),
    node_type: (["plot", "character_entry", "relation_change"] as const)[i % 3],
  }));

  const tension_curve = Array.from({ length: 120 }, (_, i) => {
    const t = i / 120;
    return +(0.3 + 0.4 * Math.sin(t * Math.PI) + 0.2 * Math.sin(t * 8 * Math.PI) + Math.random() * 0.05).toFixed(3);
  });

  return {
    meta: {
      novel_id: "",
      novel_name: "斗破苍穹",
      total_chunks: 120,
    },
    phases: [
      { name: "引入期", start: 0, end: 30, ratio: 0.25 },
      { name: "发展期", start: 30, end: 75, ratio: 0.375 },
      { name: "高潮期", start: 75, end: 105, ratio: 0.25 },
      { name: "收束期", start: 105, end: 120, ratio: 0.125 },
    ],
    nodes,
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
    total_characters: 156,
    protagonist_count: 1,
    network_density: 0.34,
    greimas_coverage: 0.85,
  };
}

export function createStyleStats(): StyleStatsMetrics {
  return {
    vocab_breadth: 0.72,
    avg_sent_len: 18.5,
    dialogue_ratio: 0.45,
  };
}

export function createCultureStats(): CultureStatsMetrics {
  return {
    idiom_density: 0.0032,
    imagery_density: 0.0058,
    classical_sentence_ratio: 0.012,
    allusion_density: 0.0019,
  };
}
