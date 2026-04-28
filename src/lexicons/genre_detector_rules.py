"""
类型检测规则配置

拆出领域规则常量与词表推荐配置，避免 genre_detector.py 同时承担规则定义和执行逻辑
"""

from __future__ import annotations

DOMAIN_KEYWORDS = {
    "xianxia": {
        "positive": ["xianxia_positive"],
        "negative": ["xianxia_negative"],
        "indicators": [
            "剑气",
            "真气",
            "灵力",
            "修仙",
            "境界",
            "丹药",
            "法宝",
            "渡劫",
            "筑基",
            "金丹",
            "元婴",
            "化神",
            "飞升",
            "仙界",
            "妖兽",
            "宗门",
            "弟子",
            "师尊",
            "道友",
        ],
    },
    "urban": {
        "positive": ["urban_positive"],
        "negative": ["urban_negative"],
        "indicators": [
            "表白",
            "求婚",
            "分手",
            "职场",
            "升职",
            "创业",
            "恋爱",
            "公司",
            "老板",
            "同事",
            "面试",
            "加班",
            "工资",
            "合同",
            "项目",
            "客户",
        ],
    },
    "power": {
        "negative": ["power_struggle"],
        "indicators": [
            "权谋",
            "阴谋",
            "暗杀",
            "夺权",
            "篡位",
            "朝堂",
            "皇帝",
            "大臣",
            "宫斗",
            "皇后",
            "妃子",
            "太子",
            "王爷",
            "将军",
            "谋反",
        ],
    },
    "shuwen": {
        "positive": ["shuwen_pattern"],
        "indicators": [
            "打脸",
            "逆袭",
            "装逼",
            "爽",
            "逆袭",
            "碾压",
            "震惊",
            "跪了",
            "服了",
            "天才",
            "废物",
            "天才变废物",
            "废物变天才",
        ],
    },
    "scifi": {
        "indicators": [
            "星际",
            "太空",
            "宇宙",
            "星系",
            "飞船",
            "机甲",
            "机器人",
            "人工智能",
            "AI",
            "芯片",
            "量子",
            "基因",
            "克隆",
            "联邦",
            "帝国",
            "跃迁",
            "黑洞",
            "虫洞",
        ],
    },
    "historical": {
        "indicators": [
            "朝代",
            "皇帝",
            "陛下",
            "圣上",
            "皇后",
            "妃子",
            "太子",
            "王爷",
            "将军",
            "宫斗",
            "后宫",
            "选秀",
            "册封",
            "夺嫡",
            "篡位",
            "谋反",
            "本宫",
            "本王",
            "微臣",
            "臣妾",
        ],
    },
    "mystery": {
        "indicators": [
            "案件",
            "命案",
            "凶杀案",
            "谋杀",
            "凶手",
            "嫌疑人",
            "侦探",
            "刑警",
            "法医",
            "证据",
            "线索",
            "推理",
            "破案",
            "真相",
            "谜团",
            "悬疑",
            "诡异",
            "神秘",
            "离奇",
            "反转",
        ],
    },
}

INDICATOR_WEIGHT = 2.0
MIN_CONFIDENCE = 0.3


def get_recommended_lexicons(genre: str) -> dict[str, list[str]]:
    """
    根据小说类型获取推荐的词表配置

    从主检测文件中拆出配置映射，让 weighted config 能独立复用
    """
    recommendations: dict[str, dict[str, list[str]]] = {
        "xianxia": {
            "pos_domains": ["xianxia_positive"],
            "neg_domains": ["xianxia_negative"],
            "fight_domains": [],
        },
        "urban": {
            "pos_domains": ["urban_positive"],
            "neg_domains": ["urban_negative"],
            "fight_domains": [],
        },
        "power": {
            "pos_domains": [],
            "neg_domains": ["power_struggle"],
            "fight_domains": ["power_struggle"],
        },
        "shuwen": {
            "pos_domains": ["shuwen_pattern"],
            "neg_domains": [],
            "fight_domains": [],
        },
        "scifi": {
            "pos_domains": [],
            "neg_domains": [],
            "fight_domains": [],
            "domain_lexicons": ["scifi_terms"],
        },
        "historical": {
            "pos_domains": [],
            "neg_domains": ["power_struggle"],
            "fight_domains": ["power_struggle"],
            "domain_lexicons": ["historical_terms"],
        },
        "mystery": {
            "pos_domains": [],
            "neg_domains": [],
            "fight_domains": [],
            "domain_lexicons": ["mystery_terms"],
        },
        "general": {
            "pos_domains": [],
            "neg_domains": [],
            "fight_domains": [],
        },
    }
    return recommendations.get(genre, recommendations["general"])
