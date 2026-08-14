"""章节结构解析入口

流程：预处理 → TOC 检测 → 候选收集 → 置信度评分 → 结构决策 → 自动分章兜底。

产出的章节字符偏移相对 preprocess_text 的输出；调用方如需按偏移切片，
必须使用同一份预处理后的文本。
"""

from __future__ import annotations

from src.chapters.candidates import collect_candidates
from src.chapters.constants import ChapterConfig
from src.chapters.models import ChapterData
from src.chapters.preprocess import preprocess_text
from src.chapters.scoring import score_candidates
from src.chapters.structure import auto_split, decide_structure, finalize
from src.chapters.toc import detect_toc_range


def parse_chapters(text: str, config: ChapterConfig | None = None) -> list[ChapterData]:
    """解析章节结构；任何文本都能得到结果（无结构时自动分章兜底）"""
    config = config or ChapterConfig()
    normalized = preprocess_text(text)

    toc_range = detect_toc_range(normalized, config)
    prologue_start = toc_range[1] if toc_range else 0

    candidates = collect_candidates(normalized, skip_range=toc_range, config=config)
    scored = score_candidates(candidates, config)

    chapters = decide_structure(normalized, scored, prologue_start, config)
    if not chapters:
        chapters = auto_split(normalized, config)

    return finalize(normalized, chapters)
