/**
 * 2026-08-31，作用：集中管理分析结果枚举的用户侧中文显示文案
 * 简要说明：已知枚举返回明确中文，未知值使用中文兜底，原始值交给调用方放入 title
 */
const LABEL_MAPS = {
  pos: {
    noun: "名词",
    verb: "动词",
    adj: "形容词",
    adjective: "形容词",
    adv: "副词",
    adverb: "副词",
    pron: "代词",
    pronoun: "代词",
    preposition: "介词",
    prep: "介词",
    conjunction: "连词",
    conj: "连词",
    numeral: "数词",
    num: "数词",
    classifier: "量词",
    quantifier: "量词",
    auxiliary: "助词",
    particle: "助词",
    interjection: "叹词",
    punctuation: "标点",
    punct: "标点",
    other: "其他",
  },
  entity: {
    person: "人物",
    character: "角色",
    group: "群体",
    organization: "组织",
    location: "地点",
    item: "物品",
    object: "物品",
  },
  dependency: {
    hed: "核心",
    sbv: "主谓",
    vob: "动宾",
    iob: "间宾",
    fob: "前置宾语",
    dbl: "兼语",
    att: "定中",
    adv: "状中",
    cmp: "动补",
    coo: "并列",
    pob: "介宾",
    lad: "左附加",
    rad: "右附加",
    is: "独立",
    wp: "标点",
    hmod: "中心修饰",
    tmod: "时间修饰",
  },
  sentence: {
    short: "短句",
    medium: "中句",
    long: "长句",
    simple: "单句",
    compound: "复句",
    complex: "复杂句",
    parallel_candidate: "并列结构",
  },
  wordLength: {
    "1": "一字词",
    "2": "二字词",
    "3": "三字词",
    "4": "四字词",
    "5_plus": "五字及以上",
    one: "一字词",
    two: "二字词",
    three: "三字词",
    four: "四字词",
    five_plus: "五字及以上",
  },
  artifactScope: {
    pretrained: "预训练词向量",
    finetuned: "微调词向量",
    pretrained_finetuned: "预训练微调词向量",
    local: "本地词表",
    global: "全局词表",
    run_owned: "本次分析生成词表",
  },
  focus: {
    single: "单主角",
    dual: "双主角",
    ensemble: "群像",
  },
  role: {
    protagonist: "推动故事",
    subject: "承担目标",
    antagonist: "制造阻碍",
    opponent: "制造阻碍",
    helper: "提供帮助",
    sender: "发起任务",
    receiver: "承接目标",
    observer: "见证事件",
    supporting: "协助推进",
    主体: "推动故事",
    主角: "推动故事",
    反对者: "制造阻碍",
    对手: "制造阻碍",
    帮助者: "提供帮助",
    帮手: "提供帮助",
    发送者: "发起任务",
    接收者: "承接目标",
  },
  relation: {
    family: "家族",
    mentor: "师徒",
    master_student: "师徒",
    subordinate: "主从",
    enemy: "敌对",
    hostile: "敌对",
    ally: "盟友",
    friendship: "友情",
    love: "爱慕",
    interest: "利益",
    leadership: "领导",
    affiliation: "隶属",
    located_in: "位于",
    same_character: "同一人物",
  },
  topicModel: {
    "gensim-lda": "概率主题模型",
    lda: "概率主题模型",
  },
} as const;

export type AnalysisLabelDomain = keyof typeof LABEL_MAPS;

/**
 * 2026-08-31，作用：将分析接口枚举转换为中文显示文案
 * 简要说明：兼容大小写和下划线，未知英文值统一显示为中文“其他”
 */
export function formatAnalysisLabel(value: string | null | undefined, domain: AnalysisLabelDomain): string {
  if (!value) return "未知";
  const normalized = value.trim().toLowerCase();
  const mapped = LABEL_MAPS[domain][normalized as keyof (typeof LABEL_MAPS)[typeof domain]];
  if (mapped) return mapped;
  return /[\u3400-\u9fff]/.test(value) ? value : "其他";
}
