"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 unified_client.py 拆分解析模块

本模块包含标注结果的解析逻辑，包括 JSON 解析和 ChunkAnnotation 构建。

修改时间: 2026-03-12
修改者: TraeAI
任务: fix-annotation-disambiguation-issues
修改内容:
- 更新 build_annotation 函数，解析 character_appearances 和 chunk_summary 新字段
- 更新 make_empty_annotation 函数，确保包含新字段的默认值
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, cast

from loguru import logger

from .schema import (
    ChunkAnnotation,
    CharacterSnapshot,
    CharacterAppearance,
    DialogueSnapshot,
    RelationChangeSnapshot,
    ClueType,
    ForeshadowingResult,
    ForeshadowingType,
    ForeshadowingConfidence,
)


@dataclass
class ThinkingExtraction:
    """思考内容提取结果"""

    thinking_content: str | None
    content_without_thinking: str
    thinking_format: Literal["reasoning_content", "think_tag", "none"]
    thinking_tokens: int


def extract_thinking_unified(
    content: str,
    reasoning_content: str | None = None,
    support_reasoning_content: bool = True,
    support_think_tags: bool = True,
) -> ThinkingExtraction:
    """
    统一提取思考内容，支持多种格式：
    1. reasoning_content 属性（DeepSeek/Qwen）- 最高优先级
    2. <think> 标签（Qwen fallback）
    3. 无思考内容
    """
    # 优先级1: reasoning_content 属性
    if support_reasoning_content and reasoning_content:
        return ThinkingExtraction(
            thinking_content=reasoning_content.strip(),
            content_without_thinking=content,
            thinking_format="reasoning_content",
            thinking_tokens=len(reasoning_content) // 2,
        )

    # 优先级2: <think> 标签
    if support_think_tags:
        think_match = re.search(r"<think>([\s\S]*?)</think>", content)
        if think_match:
            thinking = think_match.group(1).strip()
            content_clean = re.sub(r"<think>[\s\S]*?</think>\s*", "", content)
            return ThinkingExtraction(
                thinking_content=thinking,
                content_without_thinking=content_clean,
                thinking_format="think_tag",
                thinking_tokens=len(thinking) // 2,
            )

    # 无思考内容
    return ThinkingExtraction(
        thinking_content=None,
        content_without_thinking=content,
        thinking_format="none",
        thinking_tokens=0,
    )


def make_empty_annotation() -> ChunkAnnotation:
    annotation = ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        has_foreshadowing=False,
        foreshadowing_type=None,
        foreshadowing_desc="",
        character_appearances=[],
        chunk_summary="",
    )
    return annotation


def try_parse_json(content: str) -> Dict[str, Any] | None:
    """
    尝试解析 JSON，支持不完整的 JSON

    修改时间: 2026-03-17
    修改者: TraeAI
    任务: 添加 streamingjson 支持，处理 LLM 流式输出的不完整 JSON
    """
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试使用 streamingjson 修复不完整的 JSON
    try:
        import streamingjson

        lexer = streamingjson.Lexer()
        lexer.append_string(content)
        fixed = lexer.complete_json()
        data = json.loads(fixed)
        if isinstance(data, dict):
            logger.debug("json repaired by streamingjson")
            return data
    except Exception:
        pass

    # 尝试使用 fix_json 作为后备
    fixed = fix_json(content)
    if fixed is not None:
        try:
            data = json.loads(fixed)
            if isinstance(data, dict):
                logger.debug("json repaired successfully")
                return data
        except json.JSONDecodeError:
            pass
    logger.warning("json parse failed, content preview: {}", content[:200])
    return None


def extract_think_content(content: str) -> str | None:
    """从响应中提取 think 块的内容（不包含标签）"""
    match = re.search(r"<think>([\s\S]*?)</think>", content)
    if match:
        return match.group(1).strip()
    return None


def fix_json(content: str) -> str | None:
    # 移除 think 块，避免提取到思考内容中的 JSON
    content = re.sub(r"<think>[\s\S]*?</think>\s*", "", content)

    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        extracted = json_match.group(0)
        try:
            json.loads(extracted)
            logger.debug("json extracted from mixed content")
            return extracted
        except json.JSONDecodeError:
            pass
    fixed = content.strip()
    if fixed.startswith("```json"):
        fixed = fixed[7:]
    elif fixed.startswith("```"):
        fixed = fixed[3:]
    if fixed.endswith("```"):
        fixed = fixed[:-3]
    fixed = fixed.strip()
    if not fixed.startswith("{"):
        start = fixed.find("{")
        if start != -1:
            fixed = fixed[start:]
    if not fixed.endswith("}"):
        end = fixed.rfind("}")
        if end != -1:
            fixed = fixed[: end + 1]
    fixed = re.sub(r",\s*}", "}", fixed)
    fixed = re.sub(r",\s*]", "]", fixed)
    fixed = re.sub(r'(?<!\\)"(?![\s:,\}\]])"', '\\"', fixed)
    if fixed and fixed.startswith("{") and fixed.endswith("}"):
        logger.debug("json fix applied: removed markdown/code blocks, trailing commas")
        return fixed
    return None


def build_annotation(data: Dict[str, Any]) -> ChunkAnnotation:
    """
    构建标注结果

    修改时间: 2026-03-14
    修改者: TraeAI
    修改内容:
    - 支持三档 emotional_valence（positive/negative/neutral）
    - 过滤 relations 中 change 为 "无变化" 的记录
    - 过滤 character_appearances 中 clue_type 为 "none" 的记录
    """
    characters = []
    valid_role_functions = ["主体", "客体", "发送者", "接收者", "帮助者", "反对者"]
    valid_action_types = ["战斗", "逃跑", "对话", "决策", "移动", "情感", "其他"]
    valid_emotion_scores = ["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
    for c in data.get("characters", []):
        if isinstance(c, dict):
            role_function = c.get("role_function", "其他")
            if role_function not in valid_role_functions:
                role_function = "其他"
            action_type = c.get("action_type", "其他")
            if action_type not in valid_action_types:
                action_type = "其他"
            emotion_score = c.get("emotion_score", "neutral")
            if emotion_score not in valid_emotion_scores:
                emotion_score = "neutral"
            characters.append(
                CharacterSnapshot(
                    name=c.get("name", ""),
                    role_function=role_function,
                    action=c.get("action", ""),
                    action_type=action_type,
                    emotion_score=emotion_score,
                )
            )

    valid_relation_types = ["师徒", "敌对", "盟友", "爱慕", "家族", "利益", "主从"]
    relations = []
    for r in data.get("relations", []):
        if isinstance(r, dict):
            change = r.get("change", "无变化")
            if change == "无变化":
                continue
            rel_type = r.get("type", "利益")
            if rel_type not in valid_relation_types:
                rel_type = "利益"
            relations.append(
                RelationChangeSnapshot(
                    from_name=r.get("from", ""),
                    to_name=r.get("to", ""),
                    type=rel_type,
                    change=change,
                )
            )

    dialogues = []
    for d in data.get("dialogues", []):
        if isinstance(d, dict):
            dialogues.append(
                DialogueSnapshot(
                    speaker=d.get("speaker", ""),
                )
            )

    character_appearances = []
    for ca in data.get("character_appearances", []):
        if isinstance(ca, dict):
            clue_type_raw = ca.get("clue_type", "none")
            if clue_type_raw == "none":
                continue
            valid_clue_types = ["none", "self_introduction", "named_by_other", "alias_revealed", "appearance_desc"]
            clue_type: ClueType = clue_type_raw if clue_type_raw in valid_clue_types else "none"
            if clue_type == "none":
                continue
            character_appearances.append(
                CharacterAppearance(
                    raw_name=ca.get("raw_name", ""),
                    identity_clue=ca.get("identity_clue", ""),
                    clue_type=clue_type,
                )
            )

    chunk_summary = data.get("chunk_summary", "")

    valid_emotional_valences_v2 = ["positive", "negative", "neutral"]
    valid_emotional_valences_v1 = ["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
    emotional_valence = data.get("emotional_valence", "neutral")
    if emotional_valence in valid_emotional_valences_v2:
        pass
    elif emotional_valence in valid_emotional_valences_v1:
        if emotional_valence in ["strong_positive", "mild_positive"]:
            emotional_valence = "positive"
        elif emotional_valence in ["mild_negative", "strong_negative"]:
            emotional_valence = "negative"
        else:
            emotional_valence = "neutral"
    else:
        emotional_valence = "neutral"

    valid_event_types = ["冲突", "铺垫", "转折"]
    event_type = data.get("event_type", "铺垫")
    if event_type not in valid_event_types:
        event_type = "铺垫"

    has_foreshadowing = data.get("has_foreshadowing", False)
    foreshadowing_type_raw = data.get("foreshadowing_type")
    valid_foreshadowing_types = ["causal", "thematic"]
    if has_foreshadowing and foreshadowing_type_raw in valid_foreshadowing_types:
        foreshadowing_type: ForeshadowingType | None = foreshadowing_type_raw
    else:
        foreshadowing_type = None

    annotation = ChunkAnnotation(
        emotional_valence=emotional_valence,
        event_type=event_type,
        pivot_moment=data.get("pivot_moment", False),
        cliffhanger=data.get("cliffhanger", False),
        has_foreshadowing=has_foreshadowing,
        foreshadowing_type=foreshadowing_type,
        foreshadowing_desc=data.get("foreshadowing_desc", ""),
        characters=characters,
        relations=relations,
        dialogues=dialogues,
        character_appearances=character_appearances,
        chunk_summary=chunk_summary,
    )
    return annotation


def parse_foreshadowing_result(data: Dict[str, Any]) -> ForeshadowingResult:
    """
    解析伏笔分析结果

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """
    has_foreshadowing = data.get("has_foreshadowing", False)

    foreshadowing_type_raw = data.get("foreshadowing_type")
    valid_foreshadowing_types = ["causal", "thematic"]
    if has_foreshadowing and foreshadowing_type_raw in valid_foreshadowing_types:
        foreshadowing_type: ForeshadowingType | None = foreshadowing_type_raw
    else:
        foreshadowing_type = None

    confidence_raw = data.get("confidence", "high")
    valid_confidences = ["high", "medium", "low"]
    confidence: ForeshadowingConfidence = confidence_raw if confidence_raw in valid_confidences else "high"

    return ForeshadowingResult(
        has_foreshadowing=has_foreshadowing,
        foreshadowing_type=foreshadowing_type,
        anchor_text=data.get("anchor_text", ""),
        anchor_reason=data.get("anchor_reason", ""),
        confidence=confidence,
    )


def validate_foreshadowing_result(result: ForeshadowingResult, chunk_text: str) -> bool:
    """
    硬校验：anchor_text 必须是原文的真实子串。

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    返回 False 则丢弃该条记录，不入库。
    """
    if not result.has_foreshadowing:
        return True

    if result.confidence == "low":
        return False

    if not result.anchor_text or len(result.anchor_text.strip()) < 5:
        return False

    if result.anchor_text not in chunk_text:
        return False

    return True


class DisambiguationParseError(Exception):
    """人名消歧解析错误"""

    pass


def parse_alias_map(content: str, candidates: List[str] | List[Dict[str, int]]) -> Dict[str, str]:
    """
    解析消歧结果

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 支持 List[str] 和 List[Dict] 两种候选人名格式
    """
    parsed = try_parse_json(content)
    if parsed is None:
        raise DisambiguationParseError("disambiguate_characters json parse failed, content is empty or invalid")
    if not isinstance(parsed, dict):
        raise DisambiguationParseError("disambiguate_characters response not dict")
    alias_map = parsed.get("alias_map", {})
    if not isinstance(alias_map, dict):
        raise DisambiguationParseError("disambiguate_characters alias_map not dict")

    name_list: list[str] = []
    if candidates and isinstance(candidates[0], dict):
        dict_candidates = cast(list[dict[str, int]], candidates)
        name_list = [str(c["name"]) for c in dict_candidates]
    else:
        str_candidates = cast(list[str], candidates)
        name_list = list(str_candidates)

    result: dict[str, str] = {}
    for name in name_list:
        if name in alias_map:
            result[name] = str(alias_map[name])
        else:
            result[name] = name
    return result


def parse_active_entities(active_entities: str | None) -> list[str]:
    """
    解析活跃实体字符串

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer
    迁移自: annotation_client.py::_parse_active_entities

    Args:
        active_entities: 活跃实体字符串，支持多种格式

    Returns:
        解析后的人名列表
    """
    if not active_entities:
        return []
    names: list[str] = []

    if "\n" in active_entities and "- " in active_entities:
        for line in active_entities.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                name_part = line[2:]
                if "（" in name_part:
                    name = name_part.split("（")[0].strip()
                elif "：" in name_part:
                    name = name_part.split("：")[0].strip()
                elif ":" in name_part:
                    name = name_part.split(":")[0].strip()
                else:
                    name = name_part.strip()
                if name:
                    names.append(name)
    elif "\n" in active_entities:
        pass
    else:
        for part in active_entities.split(","):
            part = part.strip()
            if ":" in part:
                name = part.split(":")[0].strip()
            else:
                name = part
            if name:
                names.append(name)

    logger.debug(
        "Parsed active_entities: {} names extracted: {}",
        len(names),
        names,
    )
    return names
