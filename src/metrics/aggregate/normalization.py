"""读侧契约修复、解析与归一（§5.11、可见面契约）

从 `src/api/services/results_queries/` 收归的值级规则：存储行/模型产物的字段解析、
命名与标签归一、角色引用裁决、主题 artifact 读取与聚合行校验。全部函数只返回
纯 dict/list 载荷，不构造 API 响应模型——装配留在 api 读侧。
"""

from __future__ import annotations

import json
from math import isfinite
from typing import Any, Literal, Protocol, cast

from loguru import logger

from src.storage.path_resolver import resolve_model_dir
from src.storage.repositories import AnnotationRepository
from src.storage.repositories.graph.authority import ExportGraphAuthorityView, KnowledgeGraphAuthorityService
from src.utils.character_reference_policy import (
    decide_character_reference,
    filter_global_character_names,
)


def parse_json_field(value: Any) -> Any:
    """解析 JSON 字段，处理可能的异常"""
    if value is None:
        return None
    if isinstance(value, dict | list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def parse_int_field(value: Any) -> int | None:
    """解析整数字段，处理可能的异常"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def normalize_name_list(values: list[str] | None) -> list[str] | None:
    """2026-08-06 用于清理名称列表中的重复项并保持原有顺序"""
    if not values:
        return values

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    return normalized


def normalize_arc_scores(arc_scores: Any) -> dict[str, float] | None:
    """2026-08-06 用于把诊断角色弧评分收口为命名浮点字典"""
    if not arc_scores:
        return None

    if not isinstance(arc_scores, dict):
        return None
    normalized: dict[str, float] = {}

    for raw_name, score in arc_scores.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        try:
            normalized_score = float(score)
        except (TypeError, ValueError):
            continue

        normalized[raw_name] = normalized_score

    return normalized or None


def filter_character_list_against_arc_scores(
    values: list[str] | None,
    arc_scores: dict[str, float] | None,
) -> list[str] | None:
    """按有效角色弧线分数过滤全局角色名单"""
    if values is None:
        return None
    if not arc_scores:
        return []
    valid_names = set(arc_scores.keys())
    return [name for name in filter_global_character_names(values) if name in valid_names]


def filter_global_arc_scores(arc_scores: dict[str, float] | None) -> dict[str, float] | None:
    """创建时间: 2026-04-29 作用: 过滤未解析局部引用的角色弧线分数"""
    if not arc_scores:
        return None
    filtered = {name: score for name, score in arc_scores.items() if filter_global_character_names([name])}
    return filtered or None


def derive_focus_structure_from_characters(
    focus_characters: list[str] | None,
) -> Literal["single", "dual", "ensemble"] | None:
    """
    说明: 角色名单过滤后必须重新推导 focus_structure，
    避免把 `dual` 与单人列表这样的矛盾合同继续对外暴露
    """
    if not focus_characters:
        return None
    focus_count = len(focus_characters)
    if focus_count == 1:
        return "single"
    if focus_count == 2:
        return "dual"
    return "ensemble"


def normalize_controlled_label_list(
    values: list[str] | None,
    *,
    allowed_values: tuple[str, ...],
) -> list[str] | None:
    """规范化受控标签，非法或超过上限时返回空值"""
    if values is None:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            return None
        label = value.strip()
        if not label or label in seen:
            continue
        if label not in allowed_values:
            return None
        seen.add(label)
        normalized.append(label)

    if len(normalized) > 3:
        return None
    return normalized


def normalize_topic_labels(values: object) -> dict[str, str] | None:
    """只读取按实际 topic_id 键控的诊断标签"""
    if not isinstance(values, dict):
        return None
    normalized: dict[str, str] = {}
    for raw_id, raw_label in values.items():
        if not isinstance(raw_id, str) or not raw_id.isascii() or not raw_id.isdecimal():
            return None
        if not isinstance(raw_label, str) or not raw_label.strip():
            return None
        normalized[str(int(raw_id))] = raw_label.strip()
    return normalized


def build_name_resolution(
    annotation_repo: AnnotationRepository,
    run_id: str,
    preferred_names: list[str] | None = None,
) -> dict[str, str]:
    """2026-08-09 用于把别名角色名归一到代表角色名"""
    authority_service = KnowledgeGraphAuthorityService.from_session(annotation_repo.session)
    entities = authority_service.build_export_view(run_id).canonical_entities
    preferred = set(preferred_names or [])
    name_resolution: dict[str, str] = {}
    for entity in entities:
        aliases = [alias for alias in entity.aliases if alias and alias != entity.name]
        representative = entity.name
        if preferred:
            chosen = next((alias for alias in aliases if alias in preferred), None)
            if chosen is not None:
                representative = chosen
        for alias in aliases:
            name_resolution[alias] = representative
        if representative != entity.name:
            name_resolution[entity.name] = representative
    return name_resolution


def partition_chapter_characters(
    rows: Any,
    *,
    valid_character_names: set[str] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """按章归组角色提及，丢弃未解析的局部引用与悬空引用（可见面契约）"""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for character_row in rows:
        chapter_id = character_row.chapter_id
        raw_name = str(getattr(character_row, "surface_name", None) or character_row.name)
        decision = decide_character_reference(
            raw_name,
            resolved_global_name=getattr(character_row, "resolved_global_name", None),
        )
        character_name = decision.resolved_global_name
        if character_name is None:
            logger.warning("跳过分块角色中的未解析局部引用: chapter_id={}, name={}", chapter_id, raw_name)
            continue
        if valid_character_names is not None and character_name not in valid_character_names:
            logger.warning("跳过分块角色中的悬空引用: chapter_id={}, name={}", chapter_id, character_name)
            continue
        grouped.setdefault(chapter_id, []).append(
            {
                "name": character_name,
                "surface_name": raw_name,
                "reference_kind": getattr(character_row, "reference_kind", None) or decision.reference_kind,
                "reference_slot": getattr(character_row, "reference_slot", None) or decision.reference_slot,
                "resolved_global_name": character_name,
                "global_skip_reason": decision.global_skip_reason,
                "role_function": str(character_row.role_function) if character_row.role_function else None,
                "action": str(character_row.action) if character_row.action else None,
                "emotion_score": str(character_row.emotion_score) if character_row.emotion_score else None,
            }
        )
    return grouped


def partition_chapter_relations(
    export_graph_view: ExportGraphAuthorityView,
    *,
    valid_character_names: set[str] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """按章归组关系变化（只取 change_kind == relation）"""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for graph_change in export_graph_view.graph_changes:
        if graph_change.change_kind != "relation":
            continue
        chapter_id = graph_change.effective_chapter_id
        from_char = graph_change.from_name or ""
        to_char = graph_change.to_name or ""
        if valid_character_names is not None and (
            from_char not in valid_character_names or to_char not in valid_character_names
        ):
            logger.warning(
                "跳过分块关系中的悬空引用: chapter_id={}, from_char={}, to_char={}",
                chapter_id,
                from_char,
                to_char,
            )
            continue
        grouped.setdefault(chapter_id, []).append(
            {
                "from_char": from_char,
                "to_char": to_char,
                "from_reference_kind": None,
                "to_reference_kind": None,
                "resolved_from_global_name": from_char,
                "resolved_to_global_name": to_char,
                "reference_skip_reason": None,
                "type": graph_change.relation_type or "",
                # 2026-08-13 P2：changes 为空时兜底，避免隐式不变量破坏后 IndexError
                "change": str(graph_change.changes[0].get("change_kind") or "refine")
                if graph_change.changes
                else "refine",
            }
        )
    return grouped


def partition_chapter_dialogues(
    rows: Any,
    *,
    valid_character_names: set[str] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """按章归组对话，未解析/悬空 speaker 置空后整段无有效说话人则丢弃"""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for dialogue_row in rows:
        chapter_id = dialogue_row.chapter_id
        speakers = dialogue_row.speaker or []
        if not speakers:
            continue
        valid_speakers = []
        speaker_reference_by_surface: dict[str, dict[str, Any]] = {}
        for item in getattr(dialogue_row, "speaker_references", None) or []:
            if not isinstance(item, dict):
                continue
            surface_name = str(item.get("surface_name") or "").strip()
            if surface_name:
                speaker_reference_by_surface[surface_name] = item
        speaker_references: list[dict[str, Any]] = []
        for speaker in speakers:
            reference_payload = speaker_reference_by_surface.get(str(speaker).strip(), {})
            decision = decide_character_reference(
                speaker,
                resolved_global_name=reference_payload.get("resolved_global_name"),
            )
            speaker_references.append(
                {
                    "surface_name": decision.surface_name,
                    "reference_kind": decision.reference_kind,
                    "reference_slot": reference_payload.get("reference_slot") or decision.reference_slot,
                    "resolved_global_name": decision.resolved_global_name,
                    "can_enter_global_character": decision.can_enter_global_character,
                    "global_skip_reason": decision.global_skip_reason,
                }
            )
            normalized_speaker = decision.resolved_global_name
            if normalized_speaker is None:
                logger.warning(
                    "将章节对话中的未解析局部 speaker 置空: chapter_id={}, speaker={}",
                    chapter_id,
                    speaker,
                )
                continue
            if (
                normalized_speaker
                and valid_character_names is not None
                and normalized_speaker not in valid_character_names
            ):
                logger.warning(
                    "将章节对话中的悬空 speaker 置空: chapter_id={}, speaker={}",
                    chapter_id,
                    normalized_speaker,
                )
                continue
            if normalized_speaker:
                valid_speakers.append(normalized_speaker)
        if not valid_speakers:
            continue
        grouped.setdefault(chapter_id, []).append(
            {
                "speaker": valid_speakers,
                "speaker_references": speaker_references,
                "length": int(dialogue_row.length) if dialogue_row.length is not None else None,
            }
        )
    return grouped


class _TopicAggregationRow(Protocol):
    topic_id: object
    weighted_total: Any


def validate_topic_aggregation_row(row: object) -> tuple[int, float]:
    """2026-08-20 校验主题聚合行并返回语义化字段"""
    typed_row = cast(_TopicAggregationRow, row)
    try:
        raw_topic_id = typed_row.topic_id
        raw_weighted_total = typed_row.weighted_total
    except AttributeError as exc:
        raise RuntimeError("paragraph_topics 聚合结果缺少 topic_id 或 weighted_total 字段") from exc

    if isinstance(raw_topic_id, bool) or not isinstance(raw_topic_id, int):
        raise RuntimeError(f"paragraph_topics 聚合结果 topic_id 类型错误: {type(raw_topic_id).__name__}")
    try:
        weighted_total = float(raw_weighted_total)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"paragraph_topics 聚合结果 weighted_total 类型错误: {raw_weighted_total!r}") from exc
    if not isfinite(weighted_total) or weighted_total < 0:
        raise RuntimeError(f"paragraph_topics 聚合结果 weighted_total 必须是非负有限数: {weighted_total!r}")
    return raw_topic_id, weighted_total


def load_topic_words(
    run_id: str,
) -> tuple[dict[int, list[str]], dict[int, str], str | None]:
    """加载主题词与标签映射

    2026-09-05 A6：artifact 缺失/加载失败不再静默——第三返回值给出显式原因，
    供导出层把 topics 缺失写进 missing_fields（报告附录 B 可核查）。
    """
    model_dir = resolve_model_dir(run_id)
    topic_words_map: dict[int, list[str]] = {}
    topic_labels_map: dict[int, str] = {}

    if not model_dir.exists():
        return topic_words_map, topic_labels_map, f"topic_model_artifact_missing: {model_dir.as_posix()}"
    try:
        from src.topic import LDAConfig, LDATrainer

        trainer = LDATrainer(LDAConfig())
        topic_model = trainer.load_model(model_dir)
        for topic_id in range(topic_model.num_topics):
            topic_words = topic_model.get_topic_words(topic_id, top_n=10)
            topic_words_map[topic_id] = [word.word for word in topic_words]
            if topic_model.labels:
                label = topic_model.labels.get(topic_id)
                if label:
                    topic_labels_map[topic_id] = label
    except (FileNotFoundError, ImportError, OSError, ValueError) as exc:
        logger.warning(f"Failed to load topic model: {exc}")
        return topic_words_map, topic_labels_map, f"topic_model_load_failed: {exc}"
    return topic_words_map, topic_labels_map, None


def describe_topics_unavailability(run_id: str) -> str | None:
    """2026-09-05 A6 用于在主题聚合为空时探测显式原因（无 artifact 时不再静默消失）"""
    _, _, reason = load_topic_words(run_id)
    return reason


def read_emotion_score(value: object) -> int:
    """读取情绪分值合同：未填写视为中性 0，非 -2..2 整数直接报错"""
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool) and -2 <= value <= 2:
        return value
    raise ValueError(f"emotion={value!r}，应为 -2..2 整数或未填写的 None")
