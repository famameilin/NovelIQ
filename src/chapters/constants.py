"""章节结构解析的规则常量与阈值

参考 simple_read_pro 的 Config 设计：正则与阈值集中在本模块常量中管理，
不进入 settings.json。新增规则或调整阈值时修改本文件即可。
"""

from __future__ import annotations

import re

_CN_NUMERALS = "零一二三四五六七八九十百千万两〇○"
_CN_NUMERALS_CLASS = f"[{_CN_NUMERALS}\\d]"

# 部：第一部、上部、中部、下部
PART_RE = re.compile(
    rf"^[ \t]*(第{_CN_NUMERALS_CLASS}+部|[上中下]部)[ \t]*[：:、.\-—]*[ \t]*(.*)$",
    re.MULTILINE,
)
# 卷：第一卷、卷一、卷上、Unit 1
VOLUME_RE = re.compile(
    rf"^[ \t]*(第?{_CN_NUMERALS_CLASS}+卷|卷{_CN_NUMERALS_CLASS}+|卷[上中下]|[Uu]nit[ \t]*\d+)"
    rf"[ \t]*[：:、.\-—]*[ \t]*(.*)$",
    re.MULTILINE,
)
# 章：第一章、第1章、1章、Chapter 1（第? 可选兼容旧格式）
CHAPTER_RE = re.compile(
    rf"^[ \t]*(第?{_CN_NUMERALS_CLASS}+章|[Cc]hapter[ \t]*\d+)[ \t]*[：:、.\-—]*[ \t]*(.*)$",
    re.MULTILINE,
)
# 节：第一节、第1节、第一小节
SECTION_RE = re.compile(
    rf"^[ \t]*(第?{_CN_NUMERALS_CLASS}+节|第?{_CN_NUMERALS_CLASS}+小节)[ \t]*[：:、.\-—]*[ \t]*(.*)$",
    re.MULTILINE,
)
# 回：第一回（章回体）
HUI_RE = re.compile(
    rf"^[ \t]*(第?{_CN_NUMERALS_CLASS}+回)[ \t]*[：:、.\-—]*[ \t]*(.*)$",
    re.MULTILINE,
)
# 篇：第一篇、Part 1
ESSAY_RE = re.compile(
    rf"^[ \t]*(第?{_CN_NUMERALS_CLASS}+篇|[Pp]art[ \t]*\d+)[ \t]*[：:、.\-—]*[ \t]*(.*)$",
    re.MULTILINE,
)
# 纯名称卷：独占一行、短文本（≤4字，防正文行误报）、以 篇/卷/部 结尾（无编号，如"少年篇/风起卷/上部"）
NAMED_ESSAY_RE = re.compile(r"^[ \t]*([^ \t\r\n]{1,4}篇)[ \t]*$", re.MULTILINE)
NAMED_VOLUME_RE = re.compile(r"^[ \t]*([^ \t\r\n]{1,4}卷)[ \t]*$", re.MULTILINE)
NAMED_PART_RE = re.compile(r"^[ \t]*([^ \t\r\n]{1,4}部)[ \t]*$", re.MULTILINE)
# 英文卷：Volume 1
VOLUME_EN_RE = re.compile(
    r"^[ \t]*([Vv]olume[ \t]*\d+)[ \t]*[：:、.\-—]*[ \t]*(.*)$",
    re.MULTILINE,
)
# 番外/后记/尾声/彩蛋/外传/附录/特别篇/终章/结语（可带编号或独占一行）
# 组 1 = 类型关键词，组 2 = 可选编号，组 3 = 标题内容
EXTRA_RE = re.compile(
    rf"^(番外|后记|尾声|彩蛋|外传|附录|特别篇|终章|结语)"
    rf"(?:({_CN_NUMERALS_CLASS}+)|[ \t]+|[：:、.\-—]|[ \t]*$)"
    rf"[ \t]*[：:、.\-—]*[ \t]*(.*)$",
    re.MULTILINE,
)
# 开篇标题猜测：楔子/序章/前言 等
PRELIMINARY_TITLE_RE = re.compile(
    r"^(楔子|序言|前言|引子|序章|序幕|引言|写在前面|番外|后记|尾声|彩蛋|外传|附录|特别篇|终章|结语|Prologue)\b",
    re.IGNORECASE | re.MULTILINE,
)

# 各层级对应的编号单位（display_index_label 拼接用，extra/preface/auto 无）
LEVEL_UNITS: dict[str, str] = {
    "part": "部",
    "volume": "卷",
    "chapter": "章",
    "section": "节",
    "hui": "回",
    "essay": "篇",
}


class ChapterConfig:
    """章节解析阈值与评分权重（代码内集中管理，不进入 settings.json）"""

    # 阶段三：结构决策
    confidence_threshold: float = 0.5
    min_candidate_count: int = 1

    # 标题合理性
    min_title_length: int = 5
    max_title_length: int = 100
    max_reasonable_title_length: int = 30
    filler_prefix_chars: tuple[str, ...] = ("的", "了", "是", "在", "有", "和", "就")

    # 标题正文同行修复
    title_body_min_chars: int = 10

    # 编号连续性
    max_expected_number_delta: int = 100

    # 评分乘数（逐维度乘法叠加）
    score_short_title: float = 0.8
    score_long_title: float = 0.9
    score_normal_title: float = 1.1
    score_line_start: float = 1.1
    score_no_leading_word: float = 0.5
    score_filler_prefix: float = 0.4
    score_number_increment: float = 1.1
    score_number_decrement: float = 0.8
    score_density_even: float = 1.2
    score_density_normal: float = 1.0
    score_density_irregular: float = 0.8
    # 纯名称卷（无编号，如"少年篇"）降权，防止正文行误报
    score_named_volume: float = 0.6

    # 开篇处理
    prologue_min_chars: int = 10
    prologue_default_title: str = "序言"

    # 自动分章兜底
    fallback_title: str = "自动分章"
    fallback_chunk_size: int = 2000

    # TOC 目录页检测
    toc_enabled: bool = True
    toc_max_ratio: float = 0.1
    toc_min_entries: int = 2


# 标题正文同行修复时的断点字符
TITLE_BREAK_CHARS: tuple[str, ...] = (" ", "，", "。", "！", "？", "；", "、", ",", ".", "!", "?", ";", "：", ":")
# 句末标点（判断标题行是否混入正文）
SENTENCE_END_CHARS: tuple[str, ...] = ("。", "！", "？", "…")
