"""
标注辅助函数模块 - 例句构建和全局上下文

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆分

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数支持，使用 Repository 模式
- 2026-03-15: 使用 SQLAlchemy text() 包装 SQL 语句
- 2026-03-16: 添加变体反查表实现变体匹配

说明: 本模块包含例句构建、全局上下文抽取等辅助函数。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.config.schemas import ANNOTATION_CONFIG
from src.lexicons.loader import load_lexicon
from src.models.local.unified_client import UnifiedModelClient

if TYPE_CHECKING:
    pass


def extract_speaker_from_sentence(sentence: str) -> str | None:
    """从句子中提取说话者"""
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
                return speaker
    return None


def annotate_dialogue_structure(sentence: str) -> str:
    """标注对话结构"""
    if '"' not in sentence and "「" not in sentence and "『" not in sentence:
        return sentence
    speaker = extract_speaker_from_sentence(sentence)
    if speaker:
        return f"【说话者：{speaker}】{sentence}"
    return sentence


def compute_dialogue_lengths(text: str, speakers: list[str]) -> list[int]:
    """计算每个说话者的对话长度"""
    if not text or not speakers:
        return [0] * len(speakers)

    speaker_lengths: dict[str, int] = {speaker: 0 for speaker in speakers}

    patterns = [
        (r"「(.*?)」", 1),
        (r'"([^"]*)"', 1),
        (r'"(.*?)"', 1),
        (r"'(.*?)'", 1),
    ]

    sentences = re.split(r"[。！？\n]+", text)

    for sentence in sentences:
        speaker = extract_speaker_from_sentence(sentence)
        if speaker and speaker in speaker_lengths:
            for pattern, _ in patterns:
                matches = re.findall(pattern, sentence, re.DOTALL)
                for match in matches:
                    speaker_lengths[speaker] += len(match)

    return [speaker_lengths.get(speaker, 0) for speaker in speakers]


def build_context_sentences(
    conn,
    candidates: list[str] | list[dict],
    alias_keywords: list[str] | None = None,
    prev_chunks: int = ANNOTATION_CONFIG.prev_chunks,
) -> dict[str, str]:
    """为候选名构建上下文句子"""
    if alias_keywords is None:
        alias_keywords = ["某", "名", "号", "就是", "称号", "全名"]

    if candidates and isinstance(candidates[0], dict):
        name_list: list[str] = [c["name"] for c in candidates]  # type: ignore[index]
    else:
        name_list = list(candidates)  # type: ignore[arg-type]

    result = _build_sentence_pool(conn, name_list, alias_keywords)
    _add_prev_summaries(conn, result, name_list, prev_chunks)
    _add_identity_clues(conn, result, name_list)

    return result


def extract_new_names_from_db(
    conn, alias_map: dict, last_n_chunks: int = ANNOTATION_CONFIG.last_n_chunks, current_chunk_id: int | None = None
) -> list[dict]:
    """从数据库提取新名字"""
    known = set(alias_map.keys()) | set(alias_map.values())

    # 如果没有提供 current_chunk_id，使用数据库中的最大 chunk_id（向后兼容）
    if current_chunk_id is None:
        max_chunk_result = conn.execute(text("SELECT MAX(chunk_id) FROM chunk_characters"))
        current_chunk_id = max_chunk_result.scalar() or 0

    # 查询当前 chunk 之前最近 N 个 chunk 的名字
    min_chunk_id = max(0, current_chunk_id - last_n_chunks)

    rows = conn.execute(
        text("""
            SELECT name, COUNT(*) as count
            FROM chunk_characters
            WHERE chunk_id > :min_chunk_id AND chunk_id <= :current_chunk_id
            GROUP BY name
            ORDER BY count DESC
        """),
        {"min_chunk_id": min_chunk_id, "current_chunk_id": current_chunk_id},
    ).fetchall()

    return [{"name": r[0], "count": r[1]} for r in rows if r[0] not in known]


def build_prev_summary(annotation) -> str:
    """构建前文摘要"""
    if annotation is None:
        return ""
    parts = []
    if annotation.characters:
        names = [c.name for c in annotation.characters]
        parts.append(f"人物：{', '.join(names)}")
    parts.append(f"事件类型：{annotation.event_type}")
    parts.append(f"情感倾向：{annotation.emotional_valence}")
    return "；".join(parts)


def _load_alias_keywords() -> list[str]:
    """加载别名关键词词典"""
    lexicon_dir = Path("data/lexicons")
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
    run_id: str | None = None,
) -> str | None:
    """提取并保存全局上下文"""
    if not use_context_enhancement or resume:
        return None

    from src.context import extract_global_context, format_global_context_for_prompt, save_global_context

    first_chunks = [text for _, text in all_chunks[:3]]
    if not first_chunks:
        return None

    logger.info("extracting global context from first chunks")
    global_context = extract_global_context(first_chunks, client=annotation_client)

    if run_id:
        from src.storage.repositories import StatsRepository

        stats_repo = StatsRepository(conn)
        stats_repo.insert_global_context(
            run_id,
            novel_id,
            ",".join(global_context.get("core_characters", [])),
            global_context.get("world_setting", ""),
            novel_title,
        )
    else:
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


def _get_name_variants(name: str, name_set: set[str]) -> list[str]:
    """
    生成候选名的字符串变体。

    三字及以上的名字，额外加一个去掉第一个字（通常是姓）的版本。
    短形式已作为独立候选名存在时，不展开，避免污染两个不同人物的参考池。

    示例：
      贺重明, {"贺重明", "伯安"}     → ["贺重明", "重明"]
      贺重明, {"贺重明", "重明", "伯安"} → ["贺重明"]   ← 重明已是独立候选，不展开
      伯安,   {"伯安"}               → ["伯安"]
    """
    variants = [name]
    if len(name) >= 3:
        short = name[1:]
        if short not in name_set:
            variants.append(short)
    return variants


def _build_sentence_pool(
    conn,
    name_list: list[str],
    alias_keywords: list[str],
) -> dict[str, str]:
    """构建句子池"""
    from src.metrics.text_utils import split_sentences

    name_set = set(name_list)

    variant_to_name: dict[str, str] = {}
    for name in name_list:
        for v in _get_name_variants(name, name_set):
            variant_to_name[v] = name

    result = {}
    sentences_pool: dict[str, list[str]] = {name: [] for name in name_list}

    rows = conn.execute(text("SELECT text FROM chunks ORDER BY chunk_id")).fetchall()
    for (text_content,) in rows:
        for sentence in split_sentences(text_content):
            matched: dict[str, bool] = {}
            for variant, canonical in variant_to_name.items():
                if variant in sentence:
                    matched[canonical] = True

            for name in matched:
                annotated = _annotate_dialogue_structure(sentence)
                if any(kw in sentence for kw in alias_keywords):
                    sentences_pool[name].insert(0, annotated.strip()[: settings.analysis.sentence_preview_max_chars])
                elif len(sentences_pool[name]) < 3:
                    sentences_pool[name].append(annotated.strip()[: settings.analysis.sentence_pool_max_chars])

    for name, sents in sentences_pool.items():
        if sents:
            result[name] = " | ".join(sents[:3])

    return result


def _annotate_dialogue_structure(sentence: str) -> str:
    """标注对话结构（内部实现）"""
    return annotate_dialogue_structure(sentence)


def _add_prev_summaries(
    conn,
    result: dict[str, str],
    name_list: list[str],
    prev_chunks: int,
) -> None:
    """添加前文摘要"""
    for name in name_list:
        chunk_rows = conn.execute(
            text("""
                SELECT DISTINCT cc.chunk_id 
                FROM chunk_characters cc 
                WHERE cc.name = :name
                ORDER BY cc.chunk_id DESC LIMIT 1
            """),
            {"name": name},
        ).fetchall()

        if chunk_rows:
            chunk_id = chunk_rows[0][0]
            summaries = []
            for i in range(1, prev_chunks + 1):
                row = conn.execute(
                    text("""
                        SELECT summary FROM chunk_summaries 
                        WHERE chunk_id = :chunk_id
                    """),
                    {"chunk_id": chunk_id - i},
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
    """添加身份线索"""
    if not name_list:
        return

    appearances = conn.execute(
        text("""
            SELECT raw_name, identity_clue, clue_type 
            FROM character_appearances 
            WHERE raw_name = ANY(:names)
        """),
        {"names": name_list},
    ).fetchall()

    clue_type_labels = {
        "self_introduction": "自报身份",
        "alias_revealed": "身份提示",
        "named_by_other": "被点名",
        "appearance_desc": "外貌描述",
    }

    for raw_name, clue, clue_type in appearances:
        if raw_name in result and clue_type in clue_type_labels:
            label = clue_type_labels[clue_type]
            result[raw_name] += f" | 【{label}】{clue}"
