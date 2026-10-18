"""词表文件名常量

语义 key -> 词表文件名映射，注册关系唯一事实源；src.lexicons.registry
据此推导注册文件集合。消费方经 LEXICON_FILES["key"] 引用，不写魔法字符串。
"""

from __future__ import annotations

LEXICON_FILES: dict[str, str] = {
    "positive": "positive.txt",
    "negative": "negative.txt",
    "colloquial_positive": "colloquial_positive.txt",
    "colloquial_negative": "colloquial_negative.txt",
    "combat": "combat.txt",
    "sensory": "sensory.txt",
    "semantic_category": "semantic_category.txt",
    "function_words": "function_words.txt",
    "imagery": "imagery.txt",
    "stopwords": "stopwords.txt",
    "jieba_user_dict": "jieba_user_dict.txt",
    "negation_words": "negation_words.txt",
    "fixed_phrases": "fixed_phrases.txt",
    # 身体反应转喻（皱眉/颤抖等体态情绪信号，独立计数不进正负极性）
    "body_reaction": "body_reaction.txt",
    # 审定门（draft 词表）：命中行 is_metric_hit=false，不计入任何正式密度，
    # 逐条人工审定后再提升进 body_reaction.txt / colloquial_negative.txt
    "body_reaction_draft": "body_reaction_draft.txt",
    "colloquial_expansion_draft": "colloquial_expansion_draft.txt",
}

# draft 审定队列 key 子集：无待审词条时文件为空是合法稳态（正式表空即降级）；
# linguistic 阶段按此集合挂审定门，新增 draft 表需同时登记于此。
LEXICON_DRAFT_KEYS: tuple[str, ...] = ("body_reaction_draft", "colloquial_expansion_draft")


SEMANTIC_CATEGORY_MAPPING: dict[str, str] = {
    "武功武器类": "combat",
    "身体部件类": "body",
    "人物关系类": "relation",
    "门派派系类": "faction",
    "使令动词类": "command",
    "动作动词类": "action",
    "心理动词类": "psychology",
    "度量形容词类": "measure",
    "情绪形容词类": "emotion",
    "色彩形容词类": "color",
}
