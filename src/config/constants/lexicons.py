"""词表文件名常量（2026-08-28 常量化，原 settings.json lexicons 段 / registry.yaml）

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
    # 2026-09-05 C 批：身体反应转喻（皱眉/颤抖等体态情绪信号，独立计数不进正负极性）
    "body_reaction": "body_reaction.txt",
    # 审定门（draft 词表）：命中行 is_metric_hit=false，不计入任何正式密度，
    # 逐条人工审定后再提升进 body_reaction.txt / colloquial_negative.txt
    "body_reaction_draft": "body_reaction_draft.txt",
    "colloquial_expansion_draft": "colloquial_expansion_draft.txt",
}
