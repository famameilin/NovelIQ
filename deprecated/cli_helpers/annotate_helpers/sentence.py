"""
创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 标注辅助函数模块

本模块包含例句构建相关的函数。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.lexicons.loader import load_lexicon
from src.models.local.unified_client import UnifiedModelClient

if TYPE_CHECKING:
    pass


def _load_alias_keywords() -> list[str]:
    """
    加载别名关键词词典

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    """
    lexicon_dir = Path(__file__).resolve().parents[2] / "data" / "lexicons"
    try:
        return load_lexicon("alias_keywords", lexicon_dir)
    except FileNotFoundError:
        logger.warning("alias_keywords lexicon not found, using default")
        return []


def _extract_and_save_global_context(
    conn,
    all_chunks: list,
    novel_id: str,
    novel_title: str | None,
    use_context_enhancement: bool,
    resume: bool,
    annotation_client: UnifiedModelClient,
) -> str | None:
    """
    提取并保存全局上下文

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责从开头chunks提取全局上下文
    """
    if not use_context_enhancement or resume:
        return None

    from src.context import extract_global_context, format_global_context_for_prompt, save_global_context

    first_chunks = [text for _, text in all_chunks[:3]]
    if not first_chunks:
        return None

    logger.info("extracting global context from first chunks")
    global_context = extract_global_context(first_chunks, client=annotation_client)
    save_global_context(
        conn,
        novel_id,
        global_context.get("core_characters", []),
        global_context.get("world_setting", ""),
        novel_title,
    )
    global_context_str = format_global_context_for_prompt(global_context)
    logger.info(f"global context extracted: {len(global_context.get('core_characters', []))} core characters")

    return global_context_str


def _build_sentence_pool(
    conn,
    name_list: list[str],
    alias_keywords: list[str],
) -> dict[str, str]:
    """
    构建例句池

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 build_context_sentences 中提取，负责构建候选人名的例句池

    Returns:
        dict[str, str]: 每个名字对应的例句字符串
    """
    from src.metrics.text_utils import split_sentences

    result = {}
    sentences_pool: dict[str, list[str]] = {name: [] for name in name_list}

    rows = conn.execute("SELECT text FROM chunks ORDER BY chunk_id").fetchall()
    for (text,) in rows:
        for sentence in split_sentences(text):
            for name in name_list:
                if name in sentence:
                    annotated = _annotate_dialogue_structure(sentence)
                    if any(kw in sentence for kw in alias_keywords):
                        sentences_pool[name].insert(
                            0, annotated.strip()[: settings.analysis.sentence_preview_max_chars]
                        )
                    elif len(sentences_pool[name]) < 3:
                        sentences_pool[name].append(annotated.strip()[: settings.analysis.sentence_pool_max_chars])

    for name, sents in sentences_pool.items():
        if sents:
            result[name] = " | ".join(sents[:3])

    return result


def _annotate_dialogue_structure(sentence: str) -> str:
    """
    标注对话结构

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 annotate.py 中提取，负责标注句子中的说话者
    """
    import re

    if '"' not in sentence and "「" not in sentence and "『" not in sentence:
        return sentence

    patterns = [
        r'^([^，。！？「」『』""\s]{2,4})[说道问道答道笑道冷笑道怒道喝道叫道喊道]',
        r'[说道问道答道笑道冷笑道怒道喝道叫道喊道]([^，。！？「」『』""\s]{2,4})',
        r'^([^，。！？「」『』""\s]{2,4})[：:]["「『]',
    ]

    for pattern in patterns:
        match = re.search(pattern, sentence)
        if match:
            speaker = match.group(1).strip()
            if len(speaker) <= 4 and not any(c in speaker for c in '，。！？「」『』""'):
                return f"【说话者：{speaker}】{sentence}"

    return sentence


def _add_prev_summaries(
    conn,
    result: dict[str, str],
    name_list: list[str],
    prev_chunks: int,
) -> None:
    """
    添加前文总结

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 build_context_sentences 中提取，负责为每个名字添加前文总结
    """
    for name in name_list:
        chunk_rows = conn.execute(
            """
            SELECT DISTINCT cc.chunk_id 
            FROM chunk_characters cc 
            WHERE cc.name = ?
            ORDER BY cc.chunk_id DESC LIMIT 1
        """,
            (name,),
        ).fetchall()

        if chunk_rows:
            chunk_id = chunk_rows[0][0]
            summaries = []
            for i in range(1, prev_chunks + 1):
                row = conn.execute(
                    """
                    SELECT summary FROM chunk_summaries 
                    WHERE chunk_id = ?
                """,
                    (chunk_id - i,),
                ).fetchone()
                if row and row[0]:
                    summaries.append(row[0])

            if summaries:
                result[name] = f"【前文总结】{' | '.join(summaries)}\n{result.get(name, '')}"


def _add_identity_clues(
    conn,
    result: dict[str, str],
    name_list: list[str],
) -> None:
    """
    添加身份线索

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-cli-layer-functions
    说明: 从 build_context_sentences 中提取，负责为每个名字添加身份线索
    """
    if not name_list:
        return

    placeholders = ",".join(["?"] * len(name_list))
    appearances = conn.execute(
        """
        SELECT raw_name, identity_clue, clue_type 
        FROM character_appearances 
        WHERE raw_name IN ({})
    """.format(placeholders),
        name_list,
    ).fetchall()

    clue_type_labels = {
        "self_introduction": "自报身份",
        "alias_revealed": "身份揭示",
        "named_by_other": "被点名",
        "appearance_desc": "外貌描述",
    }

    for raw_name, clue, clue_type in appearances:
        if raw_name in result and clue_type in clue_type_labels:
            label = clue_type_labels[clue_type]
            result[raw_name] += f" | 【{label}】{clue}"
