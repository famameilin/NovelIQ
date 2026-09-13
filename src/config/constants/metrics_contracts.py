"""指标契约声明:复合数据全量注册表。

口径二分:基本数据(计数/坐标/Agent 标注原值/线程原始声明/元数据)不注册;
复合数据(聚合、比率、分布、密度、评分、统计量)逐条注册,由
tests/metrics/test_metrics_contracts.py 双向校验(声明字段须落在 response model、
stats 模型的指标字段须已声明)。原 config/metrics_contracts.yaml →
settings.json 途经定着于此:静态声明进 constants,settings.json 只留可调参数。
"""

from __future__ import annotations

METRIC_CONTRACTS: list[dict[str, object]] = [
    {
        'id': 'act_ratios',
        'concept': '叙事结构',
        'problem': '三幕比例是否失衡、高潮分布是否合理',
        'fields': [
            'act1_ratio',
            'act2_ratio',
            'act3_ratio',
        ],
        'endpoint': '/metrics/narrative-structure',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': (
            '有效章节数 < small_sample_min_chapters、缺 char_offset 进度或缺少张力/标注时均为 null；不输出 0+5% 伪'
            '归一'
        ),
        'computation_chain': '章节 Agent 标签 + 章张力 + char_offset 归一化进度 → 字符跨度三幕聚合',
        'invariants': [
            '三幕比例全部为 null 或三者之和=1',
        ],
    },
    {
        'id': 'climax_spacing',
        'concept': '叙事结构',
        'problem': '高潮间距是否过密或过疏',
        'fields': [
            'climax_spacing',
        ],
        'endpoint': '/metrics/narrative-structure',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '章张力不足或峰值 <2 时为 null；单位=归一化进度差 [0,1]',
        'computation_chain': 'paragraph_curves.surface_tension → 章均值 + char_offset 进度 → 局部峰进度间距',
        'invariants': [
            '无峰值时 null，不允许 0.0 冒充真值；单位非章序号差',
        ],
    },
    {
        'id': 'middle_collapse_index',
        'concept': '叙事结构',
        'problem': '中段是否塌陷/注水',
        'fields': [
            'middle_collapse_index',
        ],
        'endpoint': '/metrics/narrative-structure',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '有效点数 < middle_collapse_min_chunks 或首尾均值为 0 时为 null',
        'computation_chain': '章张力 + 归一化进度 → 进度 30%-70% 区间均值 / 首尾区间均值',
        'invariants': [
            '样本不足时 null，不允许 0.0',
        ],
    },
    {
        'id': 'cliffhanger_rate',
        'concept': '叙事结构',
        'problem': '章末悬念钩子密度',
        'fields': [
            'cliffhanger_rate',
        ],
        'endpoint': '/metrics/narrative-structure',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '有效标注章节数 < small_sample_min_chapters 时为 null',
        'computation_chain': '章节 Agent 标签 cliffhanger 计数 / 有效标注章数',
        'invariants': [
            '小样本 null，其余 0-1',
        ],
    },
    {
        'id': 'chapter_narrative_function_share',
        'concept': '叙事结构',
        'problem': '冲突/铺垫/转折章节占比',
        'fields': [
            'chapter_narrative_function_share',
        ],
        'endpoint': '/metrics/narrative-structure, /chapter-metrics',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '无有效标注章节时为 null；分母统一为有效标注章节数',
        'computation_chain': '章节 Agent narrative_function 枚举计数 / 有效标注章数',
        'invariants': [
            '两个端点的 share 分母一致',
        ],
    },
    {
        'id': 'lexical_pos_neg_ratio',
        'concept': '情感（词表）',
        'problem': '全书词表正面/反面比值',
        'fields': [
            'lexical_pos_neg_ratio',
        ],
        'endpoint': '/metrics/emotion-stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无任何词表密度数据时为 null',
        'computation_chain': 'paragraph_metrics positive/negative_weight_sum → 章守恒密度 → 词表正负比',
        'invariants': [
            '与 semantic polarity 为两个概念，不得混称情感基调',
        ],
    },
    {
        'id': 'semantic_polarity_distribution',
        'concept': '情感（语义）',
        'problem': '章节情感语义极性分布',
        'fields': [
            'positive_ratio',
            'negative_ratio',
            'neutral_ratio',
        ],
        'endpoint': '/metrics/emotion-stats',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '无有效标注章节时为 null',
        'computation_chain': '章节 Agent emotional_valence 五档统计',
        'invariants': [
            'positive+negative+neutral=1 或全部 null',
        ],
    },
    {
        'id': 'emotion_recovery_speed',
        'concept': '情感',
        'problem': '负向低谷后恢复速度',
        'fields': [
            'recovery_speed',
        ],
        'endpoint': '/metrics/emotion-stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无低谷、无法恢复或缺进度轴时为 null',
        'computation_chain': '章净密度 + char_offset 进度 → 低谷到回升的归一化进度距离',
        'invariants': [
            '单位=归一化进度距离 [0,1]；无低谷 null',
        ],
    },
    {
        'id': 'chapter_pivot_rate',
        'concept': '情感/叙事',
        'problem': '章节转折密度',
        'fields': [
            'chapter_pivot_rate',
        ],
        'endpoint': '/metrics/emotion-stats',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '有效标注章节数 < small_sample_min_chapters 时为 null',
        'computation_chain': '章节 Agent pivot_moment 计数 / 有效标注章数',
        'invariants': [
            '小样本 null',
        ],
    },
    {
        'id': 'arc_delta',
        'concept': '人物弧',
        'problem': '角色情感波动幅度',
        'fields': [
            'arc_delta',
        ],
        'endpoint': '/metrics/emotion-stats',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '无角色序列或全部角色样本 <2 时为 null',
        'computation_chain': 'role 角色情感序列 stdev 均值',
        'invariants': [
            '不再只有 aggregate 内部值，必须进 API/导出契约',
        ],
    },
    {
        'id': 'network_density',
        'concept': '人物网络',
        'problem': '关系是否集中于少数枢纽角色',
        'fields': [
            'network_density',
        ],
        'endpoint': '/metrics/character-stats',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '角色节点 <3 时为 null（由 0.0 改为 null 语义）',
        'computation_chain': 'authority 角色子图 → 度中心化（Freeman 集中度）',
        'invariants': [
            '只统计 entity_type=character；口径=度中心化而非图密度',
        ],
    },
    {
        'id': 'antagonist_strength_gap',
        'concept': '人物网络',
        'problem': '主体/反对者情感张力差异',
        'fields': [
            'antagonist_strength_gap',
        ],
        'endpoint': '/metrics/character-stats',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '缺主体或反对者任一侧时为 null',
        'computation_chain': '角色观察 role_function + emotion_score 绝对值均值差',
        'invariants': [
            '缺失侧 null，不输出 0.0 哨兵',
        ],
    },
    {
        'id': 'relation_change_per_10k_chars',
        'concept': '人物网络',
        'problem': '关系格局变化频率',
        'fields': [
            'relation_change_per_10k_chars',
        ],
        'endpoint': '/metrics/character-stats',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '无关系变化或总字数为 0 时为 null',
        'computation_chain': 'authority graph_changes 角色关系变化数 / 总字数 × 10000',
        'invariants': [
            'total_chars=0 时 null',
        ],
    },
    {
        'id': 'string_token_diversity',
        'concept': '语言风格',
        'problem': '连续汉字/拉丁串去重率',
        'fields': [
            'string_token_diversity',
        ],
        'endpoint': '/metrics/style-stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无文本 token 时为 null',
        'computation_chain': '全书连续汉字/拉丁串去重率（非 jieba TTR）',
        'invariants': [
            '命名标识实际口径，不得标为 TTR',
        ],
    },
    {
        'id': 'sent_len_std',
        'concept': '语言风格',
        'problem': '句长波动',
        'fields': [
            'sent_len_std',
        ],
        'endpoint': '/metrics/style-stats, /chapter-metrics',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '句子数 <2 时为 null',
        'computation_chain': '段落/章节充分统计量总体方差口径',
        'invariants': [
            '两处口径一致（总体方差）',
        ],
    },
    {
        'id': 'function_word_vector',
        'concept': '语言风格',
        'problem': '高频虚字指纹',
        'fields': [
            'function_word_vector',
        ],
        'endpoint': '/metrics/style-stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '总字符数 < function_word_min_chars 时为 null',
        'computation_chain': '20 个硬编码文言虚字出现次数 / 全书字符数',
        'invariants': [
            '短文本 null，不输出全 0 噪声',
        ],
    },
    {
        'id': 'global_emotion_rhythm_stats',
        'concept': '全局统计',
        'problem': '全书情绪与节奏波动',
        'fields': [
            'emotion_std',
            'emotion_max',
            'emotion_min',
            'rhythm_avg',
            'rhythm_std',
            'rhythm_max',
            'rhythm_min',
        ],
        'endpoint': 'export/global_stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '对应段落序列为空时不输出，或由仓库层透传 null',
        'computation_chain': 'paragraph_curves.net_density/surface_tension → 全书统计（复合→复合）',
        'invariants': [
            '从 paragraph_curves 再聚合时保留溯源链路',
        ],
    },
    {
        'id': 'lexicon_zero_hit_share',
        'concept': '全局统计',
        'problem': '情绪词典对全书真实文本的覆盖缺口有多大',
        'fields': [
            'lexicon_zero_hit_share',
        ],
        'endpoint': 'export/global_stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '全书无段落指标行时不输出（数据缺失不冒充零信号）',
        'computation_chain': (
            'paragraph_metrics.positive_weight_sum/negative_weight_sum + paragraphs.char_count → '
            '零信号段（两加权和均为 0）字符数 ÷ 有指标行段落字符数'
        ),
        'invariants': [
            '仅统计有指标行的段落；分母=有指标行段落字符和',
            '零信号≠未覆盖（确为无情绪词的段也算零信号），口径为覆盖审计线索而非质量分',
        ],
    },
    {
        'id': 'topic_distribution',
        'concept': '主题内容',
        'problem': '段落主题分布',
        'fields': [
            'topic_id',
            'weight',
        ],
        'endpoint': '/topics',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无有效训练文档时不产出；主题权重按 token 加权归一',
        'computation_chain': 'paragraph_topics + LDA 模型 → token 加权聚合',
        'invariants': [
            'num_topics 按语料规模缩放',
        ],
    },
    {
        'id': 'foreshadow_expectation',
        'concept': '伏笔回收预期',
        'problem': '伏笔是否可能回收',
        'fields': [
            'foreshadow_expectation',
        ],
        'endpoint': '/diagnosis',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '无伏笔线程或全部线程枚举证据缺失时为 null',
        'computation_chain': 'event_nodes 伏笔树根（payoff_likelihood/status/strength）确定性加权',
        'invariants': [
            '输入退化时 null，不输出恒 0.313',
        ],
    },
    {
        'id': 'graph_pagerank',
        'concept': '人物关系结构',
        'problem': '谁是核心人物（结构重要性排序，不替代 Agent 角色判定）',
        'fields': [
            'pagerank',
        ],
        'endpoint': '/graph/metrics',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无代表性人物子图（人物节点 <2）时返回 unavailable_reason；无 0 值伪造',
        'computation_chain': (
            'Agent 关系图代表性快照（别名归并、去 same_character/自环）→ 人物子图无向加权（边权=关系计数）→ PageR'
            'ank'
        ),
        'invariants': [
            '快照参数与算法版本随响应返回；结构信号不解释为阵营',
        ],
    },
    {
        'id': 'graph_hits_authority_hub',
        'concept': '人物关系结构',
        'problem': '权威人物（中心）与桥梁人物（连接多阵营）',
        'fields': [
            'hits',
        ],
        'endpoint': '/graph/metrics',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': 'HITS 不收敛时 authority/hub 为空并附 unavailable_reason',
        'computation_chain': '同一人物子图 → HITS 迭代',
        'invariants': [
            'authority/hub 为同一图快照同一算法版本',
        ],
    },
    {
        'id': 'graph_louvain_community',
        'concept': '人物关系结构',
        'problem': '结构社区识别（探索性信号，不直接等同于正派/反派阵营）',
        'fields': [
            'communities',
        ],
        'endpoint': '/graph/metrics',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '社区发现失败时为空并附原因；modularity 缺失不伪造',
        'computation_chain': '同一人物子图 → Louvain（固定 seed=42）→ 模块度',
        'invariants': [
            '固定 seed 同快照结果可复现；interpretation=structural_community_only',
        ],
    },
    {
        'id': 'textrank_keywords',
        'concept': '词共现结构',
        'problem': '语义化关键词（替代纯高频词，与 LDA 主题词对照但口径独立）',
        'fields': [
            'keywords',
        ],
        'endpoint': '/keywords',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无段落或无共现图时返回空列表与 unavailable_reason',
        'computation_chain': (
            'paragraphs.text → 句子切分 + 词元化（去除 Registry v3 停用词）→ 独立词共现图（窗口 5）→ PageRank To'
            'p-N'
        ),
        'invariants': [
            '独立词共现图，不与人物关系图混用；窗口参数随响应返回',
        ],
    },
    {
        'id': 'linguistic_pos_ratios',
        'concept': '文风基础数据',
        'problem': '重名词/重动词等用词倾向（确定性统计，与 POS 语义向量分开解释）',
        'fields': [
            'pos_ratios',
        ],
        'endpoint': '/linguistic/features',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': 'LTP 有效词元数为 0 的聚合组返回空映射并保留 token_total=0',
        'computation_chain': 'LTP 词性标签 → 词性分组映射 → 分组计数 / ltp_token_count',
        'invariants': [
            'sum(pos_ratios)=1（守恒）',
        ],
    },
    {
        'id': 'linguistic_word_length_ratios',
        'concept': '文风基础数据',
        'problem': '词长结构（二字/三字/四字/更长词分布）与节奏差异',
        'fields': [
            'word_length_ratios',
        ],
        'endpoint': '/linguistic/features',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无有效词元时返回空映射与 token_total=0',
        'computation_chain': 'LTP 词元文本长度 → 1/2/3/4/5_plus 五档计数 / ltp_token_count',
        'invariants': [
            'sum(word_length_ratios)=1（守恒）',
        ],
    },
    {
        'id': 'linguistic_sentence_patterns',
        'concept': '文风基础数据',
        'problem': '短句/长句/复句/排比候选比例（节奏风格信号）',
        'fields': [
            'sentence_pattern_ratios',
        ],
        'endpoint': '/linguistic/features',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '句子总数为 0 时返回空映射',
        'computation_chain': (
            'split_sentences 句子 → 长度档 + 连词复句 + 相邻三句首字排比候选 → 计数 / sentence_count'
        ),
        'invariants': [
            '排比为候选信号非正式修辞判定',
        ],
    },
    {
        'id': 'linguistic_dependency_depth',
        'concept': '文风基础数据',
        'problem': '句式复杂度（简单句 vs 复杂句结构差异）',
        'fields': [
            'avg_dependency_depth',
            'max_dependency_depth',
        ],
        'endpoint': '/linguistic/features',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无有效句法节点时 depth 为 null；结构信号不直接等同可读性结论',
        'computation_chain': 'LTP 依存树（ROOT=0、词元索引 1 起）→ 节点深度和 / 节点数、最大深度',
        'invariants': [
            '深度按统一坐标系计算（§C2）；节点数守恒',
        ],
    },
    {
        'id': 'linguistic_emotion_events',
        'concept': '文风基础数据',
        'problem': '谁对谁产生情绪、被否定/程度修饰的结构化情绪事件（与词典情绪对应）',
        'fields': [
            'emotion_event_count',
            'emotion_pos_event_count',
            'emotion_neg_event_count',
            'emotion_negated_event_count',
            'emotion_event_density',
            'emotion_event_holders',
            'emotion_top_predicates',
        ],
        'endpoint': '/linguistic/features',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': 'sdp 未运行或无命中事件时为 0/空列表，density 为 null（不伪造）',
        'computation_chain': (
            '情绪词典只做谓词极性候选标记 → LTP sdp AGT/DATV/mNEG/mDEPD 提供'
            '持有者/对象/否定/程度 → 词典命中谓词展开为事件（B 类本地模型判定）'
        ),
        'invariants': [
            '事件数 = 正面 + 负面事件数（守恒）',
            '持有者/对象/否定/程度全部来自 sdp 模型判定，词典不参与结构判定',
        ],
    },
    {
        'id': 'linguistic_mneg_correction',
        'concept': '文风基础数据',
        'problem': '词典否定翻转的窗口规则误差（模型习得否定辖域修正与对照）',
        'fields': [
            'lexicon_pos_count',
            'lexicon_neg_count',
            'mneg_pos_count',
            'mneg_neg_count',
            'lexicon_net',
            'mneg_net',
            'mneg_net_delta',
        ],
        'endpoint': '/linguistic/features',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '语言阶段未运行时为 null；命中集与 paragraph_metrics 同源',
        'computation_chain': (
            '同一 get_emotion_spans 命中集 → 翻转判定由 sdp mNEG（模型习得辖域）'
            '替代 negation.py 窗口规则 → 回写 paragraph_metrics 并重算段落曲线'
        ),
        'invariants': [
            'lexicon_* 与 mneg_* 命中集一致，差异仅来自翻转判定',
            'ltp.enabled=false 时不回写（paragraph_metrics 维持窗口规则口径）',
        ],
    },
    {
        'id': 'linguistic_sentence_boundary',
        'concept': '文风基础数据',
        'problem': '词典词级边界不可见的整句情绪（语气/标点强度）——句级监督按书边界',
        'fields': [
            'boundary_pos_score_sum',
            'boundary_neg_score_sum',
        ],
        'endpoint': '/linguistic/features',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': (
            '自选句标签 <2 或分值无变化（无边界可学）时为 null（不伪造 0）；'
            '逐段有分值但全正/全负时另一侧为 0（真实求和）'
        ),
        'computation_chain': (
            '标注 agent 逐章自选 2-3 句整句情绪标签（随 chapter_annotations 落库）→ '
            'LTP backbone 句向量（与 pipeline 同一模型，零新文件）→ 该书标签现算岭回归'
            '线性边界 → 全书段落逐句打分按段求和（本地 CPU，零 API 成本；按书边界，'
            '跨书曲线口径不同不可比）'
        ),
        'invariants': [
            '边界只由该书自己的标签拟合（按书自监督，无全局标定集）',
            '无标签 run 两列 NULL，段落曲线维持 mNEG 口径',
            '有分值段落两侧至少一侧非零（分值 0 不产生贡献）',
        ],
    },
    {
        'id': 'linguistic_phrase_density',
        'concept': '固定短语',
        'problem': '成语/惯用语密度（典雅典/口语/武侠风格信号）',
        'fields': [
            'fixed_phrase_density',
            'metric_hit_count',
            'four_char_candidate_count',
        ],
        'endpoint': '/linguistic/phrases',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '无词表词条或字符总数为 0 时密度 null',
        'computation_chain': (
            '版本化词表最长匹配优先（非重叠）→ is_metric_hit 命中数 ×1000 / 全书 char_count；四字候选单独计数'
        ),
        'invariants': [
            '命中区间可还原原文',
        ],
    },
    {
        'id': 'linguistic_entity_candidates',
        'concept': '实体候选',
        'problem': 'LTP 实体候选与 Agent 图谱事实的审核对照（候选不自动改图）',
        'fields': [
            'entities',
            'count_by_type',
        ],
        'endpoint': '/linguistic/entities',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '无候选时返回空列表与 unavailable_reason=no_entities',
        'computation_chain': 'LTP NER 输出 → 归一类型映射（Nh/Ni/Ns）→ 字符区间与段落定位',
        'invariants': [
            '候选不代表图谱事实；区间位于段落范围内且等于原文切片',
        ],
    },
    {
        'id': 'linguistic_entity_surface_frequency',
        'concept': '实体候选',
        'problem': '高频实体名聚合（前端 tab 展示用，不含 span 明细）',
        'fields': [
            'surface_top',
        ],
        'endpoint': '/tabs/linguistic-entities',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '无候选时返回空列表',
        'computation_chain': 'paragraph_entities 归一类型候选 → surface_text+归一类型 group-by 计数 → Top-N',
        'invariants': [
            '候选不代表图谱事实；仅回聚合计数，不透出段落定位与字符区间',
        ],
    },
    {
        'id': 'word2vec_pos_coverage',
        'concept': '词向量',
        'problem': '按词性聚合的词向量覆盖率与语义组成',
        'fields': [
            'pos_coverage',
            'pos_centroids',
        ],
        'endpoint': '/linguistic/word2vec',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': 'Word2Vec 未启用或无契约行时返回 unavailable_reason；组内无词表词时向量为空、覆盖率 null',
        'computation_chain': (
            'word2vec_model_runs 契约 + paragraph_pos_embeddings 组内加权均值 → 覆盖率=词表内词数/原始词数'
        ),
        'invariants': [
            '同维度内比较；维度与模型元数据一致；预训练文件经显式配置 model_dir 登记使用',
        ],
    },
    {
        'id': 'word2vec_pos_similarity',
        'concept': '词向量',
        'problem': '词性组语义空间的相对位置（质心余弦相似度矩阵，供热力图展示）',
        'fields': [
            'pos_similarity_matrix',
        ],
        'endpoint': '/linguistic/word2vec',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '质心少于 2 组、维度不一致或存在零向量时返回 null',
        'computation_chain': 'paragraph_pos_embeddings 质心（词表内词数加权均值）→ 组间余弦相似度矩阵',
        'invariants': [
            '矩阵对称、对角线为 1；行序与 pos_centroids 一致（pos_group 升序）；同维度内比较',
        ],
    },
    {
        'id': 'lexical_density',
        'concept': '情感（词表）',
        'problem': '章级与书级词表正/负/净情绪密度',
        'fields': [
            'pos_density',
            'neg_density',
            'net_density',
        ],
        'endpoint': '/chapter-metrics',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': (
            '分母（有效段落 token 总数）≤0 时为 None（_safe_ratio）；缺指标行段落整段剔除；纯空章节不产出'
        ),
        'computation_chain': (
            'paragraph_metrics.positive/negative_weight_sum → 章内求和 / Σtoken_count；书级=跨章分子分母再求和（'
            '非章均值）'
        ),
        'invariants': [
            '三密度同分母（token）；段落级同名字段（paragraph-curves）为基本数据不在本契约',
        ],
    },
    {
        'id': 'rhetoric_density',
        'concept': '语言风格',
        'problem': '战斗词/感叹/疑问/停顿/对话占比',
        'fields': [
            'fight_density',
            'exclaim_per_100_chars',
            'question_per_100_chars',
            'pause_per_100_chars',
            'dialogue_ratio',
        ],
        'endpoint': '/chapter-metrics, /metrics/style-stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '分母（Σtoken 或 Σchar）≤0 时为 None；无 0.0 哨兵',
        'computation_chain': (
            'fight=COMBAT_TERMS fuzzy（编辑距离≤1）命中 / Σtoken；exclaim/question/pause=计数×100/Σchar；dialog'
            'ue=Σdialogue_char_count/Σchar_count'
        ),
        'invariants': [
            'per_100_chars 分母=字符数，fight 分母=token 数，不得混用',
        ],
    },
    {
        'id': 'vocabulary_diversity',
        'concept': '语言风格',
        'problem': '词汇丰富度（TTR/MTLD 两口径）',
        'fields': [
            'ttr',
            'mtld',
            'avg_ttr',
            'avg_mtld',
        ],
        'endpoint': '/chapter-metrics, export/global_stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': 'tokens 为空时 None；mtld 全唯一词（factors=0）返回 None；stats 表无行时 avg_* 为 None',
        'computation_chain': (
            'ttr=去重词数/token 数；mtld=windowed TTR 因子法（阈值 settings.metrics.mtld_threshold）；avg_ttr/avg_m'
            'tld=全书 token 序列单值'
        ),
        'invariants': [
            (
                'avg_ttr/avg_mtld 名为 avg 实为全书单值，非章均值；与 string_token_diversity（连续串去重率）三口径'
                '并存，不得互标'
            ),
        ],
    },
    {
        'id': 'sent_len_avg',
        'concept': '语言风格',
        'problem': '平均句长',
        'fields': [
            'avg_sent_len',
        ],
        'endpoint': '/metrics/style-stats, /chapter-metrics, export/global_stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': 'sentence_count≤0 时为 None',
        'computation_chain': 'Σsentence_char_sum / Σsentence_count（段落/章节充分统计量守恒聚合）',
        'invariants': [
            '与 sent_len_std 同源充分统计量',
        ],
    },
    {
        'id': 'dialogue_tone_distribution',
        'concept': '语言风格（对话）',
        'problem': '对话语气分布',
        'fields': [
            'tone_distribution',
        ],
        'endpoint': '/metrics/style-stats',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '无有效 tone 标注时为 {}（空 dict 非 None）',
        'computation_chain': 'Agent 对话标注 tone（DialogueRecord）→ 各 tone 计数 / 有效 tone 总数',
        'invariants': [
            '输入为云端 Agent 对话标注，非词表判定',
        ],
    },
    {
        'id': 'semantic_category_density',
        'concept': '语言风格',
        'problem': '语义类别词密度与平均词长',
        'fields': [
            'category_density',
            'avg_word_len',
        ],
        'endpoint': '/metrics/style-stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': (
            'category_density 空文本/0 token 时输出全 0.0 dict（既有 0.0 哨兵）；无键时契约层为 None；avg_word_len '
            '空文本为 0.0（哨兵）'
        ),
        'computation_chain': (
            'SEMANTIC_CATEGORIES 词表 count_mixed_hits / Σjieba token，min(…,1.0)；avg_word_len=jieba 词均长'
        ),
        'invariants': [
            '单类别密度上限 1.0；两处 0.0 哨兵待后续收敛为 null',
        ],
    },
    {
        'id': 'climax_profile',
        'concept': '叙事结构',
        'problem': '高潮数量/位置/高度/升级趋势',
        'fields': [
            'climax_count',
            'climax_positions',
            'climax_heights',
            'peak_escalation',
            'dominant_climax_pos',
        ],
        'endpoint': '/metrics/narrative-structure',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': (
            '小样本（有效点<small_sample_min_chapters）或进度不可用→脚手架：count=0、positions/heights=[]（空态哨'
            '兵）；peak_escalation 峰数<3 时 None'
        ),
        'computation_chain': (
            '标注章∩张力章对齐→章起点 char_offset 归一化进度+章内 surface_tension 均值→局部峰→heights=峰张力/最'
            '大张力→peak_escalation=heights 对序号最小二乘斜率三档枚举'
        ),
        'invariants': [
            'positions/heights 为空列表是空态哨兵非真值；dominant=最高峰位（可被 representative_peak_idx 覆盖）',
        ],
    },
    {
        'id': 'book_annotation_shares',
        'concept': '叙事结构',
        'problem': '书级悬念率与情感基调占比（book 口径）',
        'fields': [
            'chapter_cliffhanger_rate',
            'chapter_emotional_valence_share',
        ],
        'endpoint': '/chapter-metrics',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '有效标注章数=0 时 rate 为 None；share 为空 dict',
        'computation_chain': '章节 Agent cliffhanger/emotional_valence 标签计数 / 非 None 标注章数',
        'invariants': [
            '分母=有效标注章（缺失标注剔除），与 /metrics/narrative-structure 的 cliffhanger_rate 同口径',
        ],
    },
    {
        'id': 'emotion_trend_windows',
        'concept': '情感（词表）',
        'problem': '情绪覆盖与密度的滑窗序列（展示层）',
        'fields': [
            'pos_coverage',
            'neg_coverage',
            'pooled_pos_density',
            'pooled_neg_density',
            'pooled_net_density',
            'smoothed_pos_coverage',
            'smoothed_neg_coverage',
            'smoothed_pooled_pos_density',
            'smoothed_pooled_neg_density',
            'smoothed_pooled_net_density',
        ],
        'endpoint': '/emotion-trend',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': (
            'range 内无段落→[]；窗内 token_total≤0→pooled_* 为 None（coverage 恒数值）；窗数<lowess_min_points '
            '或窗内原值全 None→smoothed_* 为 None'
        ),
        'computation_chain': (
            'paragraphs+paragraph_metrics 按 window_paragraphs（钳 5~40）段切窗→coverage=命中段/段落数，pooled=Σw'
            'eight/Σtoken→LOWESS（权重=max(token_total,1)，bandwidth=0.02）平滑；smoothed coverage 钳 [0,1]'
        ),
        'invariants': [
            'coverage 分母=段落数，pooled 分母=token 数；窗口聚合属展示层，平滑值不作指标结论',
        ],
    },
    {
        'id': 'lexical_emotion_trend_label',
        'concept': '情感（词表）',
        'problem': '章净密度前/中/后趋势标签',
        'fields': [
            'lexical_emotion_trend',
        ],
        'endpoint': '/metrics/emotion-stats',
        'category': 'A',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '净密度样本<3 时为 None',
        'computation_chain': '章级 net_density 序列→前/中/后趋势判定（字符串标签）',
        'invariants': [
            '值为趋势标签非数值序列；窗口数值序列在 /emotion-trend，两者不得混用',
        ],
    },
    {
        'id': 'character_role_function_stats',
        'concept': '人物网络',
        'problem': '角色主导功能与其占比/分布',
        'fields': [
            'dominant_role_function',
            'dominant_role_ratio',
            'role_function_distribution',
        ],
        'endpoint': '/characters',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': '观察缺 role_function 记 unknown 参与计数；恒非空',
        'computation_chain': (
            '章节 Agent 角色观察 role_function（枚举主体/客体/发送者/接收者/帮助者/反对者）按规范名归并→计数与 arg'
            'max'
        ),
        'invariants': [
            'distribution 含 unknown 键；ratio 分母=appearance_count',
        ],
    },
    {
        'id': 'character_focus_stats',
        'concept': '人物弧',
        'problem': '叙事聚焦度/聚焦身份/角色情绪均值',
        'fields': [
            'narrative_focus_score',
            'is_focus_character',
            'avg_emotion_score',
        ],
        'endpoint': '/characters',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': (
            '无诊断记录或缺 diagnosis 名单→focus_score None、is_focus False；avg_emotion_score 恒数值（缺失情绪按 '
            '0 计入）'
        ),
        'computation_chain': (
            'focus_score=0.25×（appearance/max）+0.25×（主体占比）+0.25×（arc_score/10）+0.25×（∈main_characte'
            'rs），输入经别名归一；is_focus=∈focus_characters；avg_emotion=emotion 分值（-2..2）均值'
        ),
        'invariants': [
            '输入含云端诊断名单与 Agent 情绪标注，代码仅加权',
        ],
    },
    {
        'id': 'network_structure_stats',
        'concept': '人物网络',
        'problem': '逐角色度中心性与角色功能覆盖度',
        'fields': [
            'degree_centrality',
            'greimas_coverage',
            'function_coverage_distribution',
        ],
        'endpoint': '/metrics/character-stats',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': (
            '无关系→degree_centrality 契约层 None；无角色功能→greimas_coverage 0.0（哨兵）；coverage 空输入全键 0'
            '.0→契约层 None'
        ),
        'computation_chain': (
            '确认关系角色子图→degree_centrality=逐角色 度/(n-1)；greimas=|role_functions∩六功能|/6；function_cove'
            'rage=PROPP_FUNCTIONS 7 键占比'
        ),
        'invariants': [
            'degree_centrality 无 <3 门控，与 network_density（Freeman 集中度）同图不同指标',
        ],
    },
    {
        'id': 'diagnosis_composite',
        'concept': '诊断复合判定',
        'problem': '类型/风格/主题标签与价值观/权力/文化深度复合评分',
        'fields': [
            'arc_scores',
            'genre_labels',
            'style_labels',
            'topic_labels',
            'value_logic_type',
            'power_stance_score',
            'common_people_dignity',
            'cultural_depth_score',
            'narrative_arc_type',
            'theme_color',
            'focus_structure',
        ],
        'endpoint': '/diagnosis',
        'category': 'C',
        'objective_subjective': 'subjective',
        'authoritative': True,
        'null_semantics': (
            '无诊断记录→全 None；genre/style 非法标签或超 3 个→整体 None；power_stance/dignity 解析失败 None；foc'
            'us_structure 由 focus 名单派生（1/2/≥3→single/dual/ensemble）'
        ),
        'computation_chain': (
            '诊断 Agent 输出→写库 schema 校验（枚举/hex 色/0-5 int/arc 0-10）→读路径清洗（剔未解析局引、去重保序'
            '、_parse_int_field）'
        ),
        'invariants': [
            'labels 为闭合枚举且上限 3；focus_structure 为代码派生可与 Agent 原值不同；theme_color=#RGB/#RRGGBB',
        ],
    },
    {
        'id': 'topic_aggregate_distribution',
        'concept': '主题内容',
        'problem': '全书/章节级主题聚合分布',
        'fields': [
            'distribution',
        ],
        'endpoint': '/topics/aggregate',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': (
            '无 topic_model_runs 契约行或 token_total≤0→None+unavailable_reason；章节 token_total=0→该章 None'
        ),
        'computation_chain': (
            'paragraph_topics × inference_token_count→Σ(weight×token)/Σtoken（入模 token 加权）→补零至 num_to'
            'pics 维'
        ),
        'invariants': [
            '分母=入模 token（非源 token）；level=book|chapter 两级同公式',
        ],
    },
    {
        'id': 'topic_shift_jsd',
        'concept': '主题内容',
        'problem': '相邻窗口主题分布漂移（JS 散度）',
        'fields': [
            'score',
        ],
        'endpoint': '/topics/shifts',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': (
            '<2 段→[]+insufficient_windows；窗口 token<min_tokens_per_window 整窗跳过；全未达阈值→[]+no_candidate'
            's'
        ),
        'computation_chain': (
            '相邻不重叠 window_size=10 段窗口（入模 token 加权分布）→底 2 JS 散度 [0,1]；score<score_threshold（0.'
            '3）剔除；max_candidates=50 截断'
        ),
        'invariants': [
            '候选点=右窗首段 start_position；生效配置回显 response.config',
        ],
    },
    {
        'id': 'topic_emotion_affinity',
        'concept': '主题内容',
        'problem': '主题×情绪关联（主题平均净密度）',
        'fields': [
            'emotion',
            'weighted_token_total',
        ],
        'endpoint': '/topics/emotion',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': (
            '无模型行→[]+topic_inference_unavailable；无曲线行→[]+no_emotion_rows；单主题分母≤0→该条 None'
        ),
        'computation_chain': (
            'ParagraphTopic ⋈ Inference ⋈ paragraph_curves→Σ(weight×token×net_density)/Σ(weight×token)；weigh'
            'ted_token_total=Σ(weight×token)'
        ),
        'invariants': [
            'net_density 为词表法原始值（未平滑）；正常时恒返回 num_topics 条',
        ],
    },
    {
        'id': 'dependency_structure',
        'concept': '文风基础数据',
        'problem': '依存关系配比与依存森林根数',
        'fields': [
            'dependency_relation_ratios',
            'dependency_root_count',
        ],
        'endpoint': '/linguistic/features',
        'category': 'B',
        'objective_subjective': 'objective',
        'authoritative': True,
        'null_semantics': '组内 dep_node_total=0→{}（空 dict）；整个 run 无特征行→全 None+linguistic_unavailable',
        'computation_chain': (
            'LTP 依存弧按关系计数→Σcounts/Σdep_node（分母=依存弧总数，非 token/句数）；root_count=各段 head=0 弧'
            '数求和（≈句数）'
        ),
        'invariants': [
            'ratios 分母=依存弧总数；与 avg/max_dependency_depth 同分母',
        ],
    },
]
