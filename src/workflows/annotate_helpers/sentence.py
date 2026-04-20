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

修改时间: 2026-03-21
修改者: TraeAI
任务: refactor-phase3-to-annotation-layer
修改内容: 将对话归属判断相关函数迁移到 models/local/annotation/phase3.py，
         保留向后兼容的导入

修改时间: 2026-04-06
修改者: GLM-5
任务: 移除向后兼容代码
修改内容: 移除 _load_alias_keywords 死代码和旧 loader 导入

说明: 本模块包含例句构建、全局上下文抽取等辅助函数。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.models.disambiguation_types import NameCountCandidate
from src.models.interfaces import AnnotationLike

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


def build_context_sentences(
    conn,
    candidates: list[NameCountCandidate],
    alias_keywords: list[str] | None = None,
    run_id: str | None = None,
    max_chunk_id: int | None = None,
) -> dict[str, str]:
    """为候选名构建上下文句子

    修改时间: 2026-03-30
    修改者: TraeAI
    任务: feature/chunk-summary-timeline-only
    修改内容: 移除 _add_prev_summaries 调用，summary 仅用于 Timeline 展示，不参与消歧证据链
    """
    if not run_id:
        raise ValueError("run_id is required for build_context_sentences")
    if alias_keywords is None:
        alias_keywords = ["某", "名", "号", "就是", "称号", "全名"]

    name_list = [candidate["name"] for candidate in candidates]

    result = _build_sentence_pool(conn, name_list, alias_keywords, run_id, max_chunk_id=max_chunk_id)
    _add_identity_clues(conn, result, name_list, run_id, max_chunk_id=max_chunk_id)

    return result


async def _extract_and_save_global_context(
    conn,
    all_chunks: list,
    novel_id: str,
    novel_title: str | None,
    use_context_enhancement: bool,
    resume: bool,
    annotation_client: AnnotationLike,
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
    global_context = await extract_global_context(first_chunks, client=annotation_client)

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
    run_id: str,
    max_chunk_id: int | None = None,
) -> dict[str, str]:
    """构建句子池。

    修改时间: 2026-04-01
    修改者: CodeBuddy
    任务: P1 候选质量治理 - 例句池优先级优化
    修改内容: 分离高优命名句和普通句，命名句优先入选
    """
    from src.metrics.text_utils import split_sentences

    name_set = set(name_list)

    variant_to_name: dict[str, str] = {}
    for name in name_list:
        for v in _get_name_variants(name, name_set):
            variant_to_name[v] = name

    # Split into high-priority and normal pools
    HIGH_PRIORITY_KEYWORDS = (
        "叫作",
        "名为",
        "取名",
        "原名",
        "别名",
        "号称",
        "本名",
        "全名",
        "字",
        "号",
        "就是",
        "其实",
    )
    high_pool: dict[str, list[str]] = {name: [] for name in name_list}
    normal_pool: dict[str, list[str]] = {name: [] for name in name_list}

    if max_chunk_id is None:
        rows = conn.execute(
            text("SELECT text FROM chunks WHERE run_id = :run_id ORDER BY chunk_id"),
            {"run_id": run_id},
        ).fetchall()
    else:
        rows = conn.execute(
            text("SELECT text FROM chunks WHERE run_id = :run_id AND chunk_id <= :max_chunk_id ORDER BY chunk_id"),
            {"run_id": run_id, "max_chunk_id": max_chunk_id},
        ).fetchall()
    for (text_content,) in rows:
        for sentence in split_sentences(text_content):
            matched: dict[str, bool] = {}
            for variant, canonical in variant_to_name.items():
                if variant in sentence:
                    matched[canonical] = True

            for name in matched:
                annotated = _annotate_dialogue_structure(sentence)
                truncated = annotated.strip()[: settings.analysis.sentence_pool_max_chars]

                # High-priority: contains naming keywords
                if any(kw in sentence for kw in HIGH_PRIORITY_KEYWORDS):
                    if len(high_pool[name]) < 2:
                        high_pool[name].append(truncated)
                # Alias keywords: insert at head of normal pool
                elif any(kw in sentence for kw in alias_keywords):
                    if len(normal_pool[name]) < 3:
                        normal_pool[name].insert(0, truncated)
                # Normal: append
                elif len(normal_pool[name]) < 3:
                    normal_pool[name].append(truncated)

    # Merge: high-priority first, then normal
    result = {}
    for name in name_list:
        merged = high_pool[name] + normal_pool[name]
        if merged:
            result[name] = " | ".join(merged[:3])

    # 稀有名（≤2次出现）不受例句数量限制，确保包含所有可用上下文
    # 查询各名字的出现次数，对稀有名放宽限制
    # 注意：speaker 是 text[] 类型，需要用 SQLAlchemy ORM 查询以正确处理数组
    if name_list:
        from src.storage.models.annotation import ChunkCharacter, ChunkDialogue

        name_set_for_count = set(name_list)
        counts_dict: dict[str, int] = {}

        char_rows = (
            conn.query(ChunkCharacter.name)
            .filter(ChunkCharacter.run_id == run_id)
            .filter(ChunkCharacter.name.in_(name_list))
        )
        if max_chunk_id is not None:
            char_rows = char_rows.filter(ChunkCharacter.chunk_id <= max_chunk_id)
        char_rows = char_rows.all()
        for row in char_rows:
            if row.name:
                counts_dict[row.name] = counts_dict.get(row.name, 0) + 1

        dialogue_rows = (
            conn.query(ChunkDialogue.speaker)
            .filter(ChunkDialogue.run_id == run_id)
            .filter(ChunkDialogue.speaker.isnot(None))
        )
        if max_chunk_id is not None:
            dialogue_rows = dialogue_rows.filter(ChunkDialogue.chunk_id <= max_chunk_id)
        dialogue_rows = dialogue_rows.all()
        for row in dialogue_rows:
            for s in row.speaker or []:
                if s in name_set_for_count:
                    counts_dict[s] = counts_dict.get(s, 0) + 1

        rare_counts = {name: cnt for name, cnt in counts_dict.items() if cnt <= 2}
        for name in rare_counts:
            # 稀有名：重新扫描所有句子，不受 pool 大小限制
            rare_sentences: list[str] = []
            for (text_content,) in rows:
                for sentence in split_sentences(text_content):
                    if any(v in sentence for v in _get_name_variants(name, name_set)):
                        truncated = _annotate_dialogue_structure(sentence).strip()[
                            : settings.analysis.sentence_pool_max_chars
                        ]
                        if truncated not in rare_sentences:
                            rare_sentences.append(truncated)
            if rare_sentences:
                result[name] = " | ".join(rare_sentences)

    return result


def _annotate_dialogue_structure(sentence: str) -> str:
    """标注对话结构（内部实现）"""
    return annotate_dialogue_structure(sentence)


def _add_identity_clues(
    conn,
    result: dict[str, str],
    name_list: list[str],
    run_id: str,
    max_chunk_id: int | None = None,
) -> None:
    """添加身份线索

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: use-phase3-identity-clue-in-disambiguation
    修改内容: 从 chunk_dialogues 表获取 Phase 3 提取的身份线索，替代 character_appearances 表

    修改时间: 2026-04-08
    修改者: TraeAI
    任务: fix-multi-speaker-support
    修改内容: speaker 改为 text[] 数组，使用 ORM 查询替代 unnest() SQL
    """
    if not name_list:
        return

    from src.storage.models.annotation import ChunkDialogue

    name_set = set(name_list)
    dialogues = (
        conn.query(ChunkDialogue.speaker, ChunkDialogue.identity_clue)
        .filter(ChunkDialogue.run_id == run_id)
        .filter(ChunkDialogue.identity_clue.isnot(None))
        .filter(ChunkDialogue.identity_clue != "")
    )
    if max_chunk_id is not None:
        dialogues = dialogues.filter(ChunkDialogue.chunk_id <= max_chunk_id)
    dialogues = dialogues.all()

    for row in dialogues:
        if row.identity_clue:
            for speaker_name in row.speaker or []:
                if speaker_name in name_set and speaker_name in result:
                    result[speaker_name] += f" | 【身份线索】{row.identity_clue}"
                elif speaker_name in name_set:
                    result[speaker_name] = f"【身份线索】{row.identity_clue}"
