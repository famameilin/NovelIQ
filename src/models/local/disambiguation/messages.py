"""消歧消息构建模块。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.config import settings
from src.config.schemas.annotation import ANNOTATION_CONFIG
from src.models.disambiguation_types import NameCountCandidate

from ..prompts import ANONYMOUS_DISAMBIG_SYSTEM_PROMPT, DISAMBIGUATE_SYSTEM_PROMPT
from .evidence import build_evidence_profile, format_evidence_profile

if TYPE_CHECKING:
    from .evidence import EvidenceProfile

_EVIDENCE_MARKERS = {
    "前文总结": "前文摘要-弱证据",
    "自报身份": "身份线索",
    "身份提示": "身份线索",
    "被点名": "身份线索",
    "外貌描写": "身份线索",
    "独特标记": "身份线索",
    "亲缘身份": "身份线索",
    "命名场景": "身份线索",
    "身份线索": "身份线索",
}

_EVIDENCE_MARKER_PATTERN = re.compile(r"【(前文总结|自报身份|身份提示|被点名|外貌描写|独特标记|亲缘身份|命名场景|身份线索)】")
_EVIDENCE_PREFIXES = tuple(f"【{marker}】" for marker in _EVIDENCE_MARKERS)


def _has_original_sentence_content(context: str) -> bool:
    remaining = context.strip()
    if not remaining:
        return False

    if remaining.startswith("【前文总结】"):
        _, separator, tail = remaining.partition("\n")
        if not separator:
            return False
        remaining = tail.strip()
        if not remaining:
            return False

    for segment in remaining.split(" | "):
        normalized = segment.strip()
        if not normalized:
            continue
        if normalized.startswith(_EVIDENCE_PREFIXES):
            continue
        return True

    return False


def _extract_evidence_types_from_context(context: str) -> list[str]:
    """从上下文字符串中提取证据类型。"""
    evidence_types: list[str] = []

    matches = _EVIDENCE_MARKER_PATTERN.findall(context)
    for match in matches:
        evidence_type = _EVIDENCE_MARKERS.get(match)
        if evidence_type and evidence_type not in evidence_types:
            evidence_types.append(evidence_type)

    if context and _has_original_sentence_content(context):
        evidence_types.append("原文例句")

    return evidence_types


def _format_evidence_annotation(evidence_types: list[str]) -> str:
    """格式化证据来源标注。"""
    if not evidence_types:
        return ""
    return "【证据来源：" + "、".join(evidence_types) + "】"


def _format_candidate_block(name: str, count: int, context: str, evidence_profile: EvidenceProfile) -> str:
    """构建更结构化的候选项描述。"""

    lines = [
        f"- 候选称呼：{name}",
        f"  次数：{count}",
        f"  {format_evidence_profile(evidence_profile)}",
    ]
    if context:
        lines.append(f"  参考上下文：{context}")
    return "\n".join(lines)


def build_existing_character_hint(
    existing_names: list[str] | None,
    existing_context_sentences: dict[str, str] | None = None,
) -> str | None:
    """构建已有角色锚点提示。"""

    if not existing_names:
        return None

    lines = ["【已存在角色锚点】"]
    for name in existing_names:
        context = (existing_context_sentences or {}).get(name, "").strip()
        evidence_profile = build_evidence_profile(context)
        lines.append(f"- {name}")
        lines.append(f"  {format_evidence_profile(evidence_profile)}")
        if context:
            lines.append(f"  参考上下文：{context}")

    return "\n".join(lines)


_RELATION_TYPE_DESCRIPTIONS: dict[str, str] = {
    "belongs_to": "人物属于某组织（如 伯安 belongs_to 贺家）",
    "member_of": "人物是某群体成员（如 张三 member_of 赵甲卫）",
    "leader_of": "人物是某群体或组织的首领（如 贺重明 leader_of 贺家）",
    "affiliated_with": "群体隶属于某组织（如 赵甲卫 affiliated_with 贺家）",
    "father_of": "A 是 B 的父亲（如 贺军 father_of 贺大山）",
    "son_of": "A 是 B 的儿子（如 贺大山 son_of 贺军）",
    "parent_of": "A 是 B 的父母（如 赵兰英 parent_of 伯安）",
    "child_of": "A 是 B 的子女（如 伯安 child_of 赵兰英）",
    "sibling_of": "A 是 B 的兄弟姐妹（如 伯安 sibling_of 贺重明）",
    "spouse_of": "A 是 B 的配偶（如 赵兰英 spouse_of 贺铎）",
}

_ENTITY_TYPE_DESCRIPTIONS: dict[str, str] = {
    "character": "具体人物角色（如伯安、贺重明、柳婉儿）",
    "group": "群体/队伍统称（如赤甲卫、禁军、一队）",
    "organization": "组织/门派/家族（如贺家、玄天道宗）",
    "creature": "灵兽/物种泛称（如灵禽、赤焰驹、白鹤）",
    "artifact": "法宝/器物（如灵剑、玉佩、符箓）",
}


def _build_relation_types_section() -> str:
    """根据配置动态构建关系类型说明。"""
    valid_types = settings.analysis.valid_relation_types
    lines = ["【关系类型说明】"]
    for rel_type in valid_types:
        desc = _RELATION_TYPE_DESCRIPTIONS.get(rel_type, f"{rel_type} 关系")
        lines.append(f"- {rel_type}：{desc}")
    return "\n".join(lines)


def _build_relation_types_union() -> str:
    """构建关系类型联合字符串，用于 JSON 格式说明。"""
    valid_types = settings.analysis.valid_relation_types
    return "|".join(valid_types)


def _build_entity_types_section() -> str:
    """根据配置动态构建实体类型说明。"""
    valid_types = ANNOTATION_CONFIG.valid_entity_types
    lines = ["【实体类型识别规则】"]
    for etype in valid_types:
        desc = _ENTITY_TYPE_DESCRIPTIONS.get(etype, f"{etype} 类型")
        lines.append(f"- {etype}：{desc}")
    return "\n".join(lines)


def _build_entity_types_union() -> str:
    """构建实体类型联合字符串，用于 JSON 格式说明。"""
    valid_types = ANNOTATION_CONFIG.valid_entity_types
    return "|".join(valid_types)


def _build_dynamic_system_prompt() -> str:
    """将动态关系类型和实体类型填入系统提示词模板。"""
    base_prompt = DISAMBIGUATE_SYSTEM_PROMPT
    base_prompt = base_prompt.replace("{{RELATION_TYPES_UNION}}", _build_relation_types_union())
    base_prompt = base_prompt.replace("{{RELATION_TYPES_SECTION}}", _build_relation_types_section())
    base_prompt = base_prompt.replace("{{ENTITY_TYPES_UNION}}", _build_entity_types_union())
    base_prompt = base_prompt.replace("{{ENTITY_TYPES_SECTION}}", _build_entity_types_section())
    return base_prompt


def build_disambiguate_messages(
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str] | None = None,
    existing_names: list[str] | None = None,
    rag_hint: str | None = None,
) -> list[dict[str, str]]:
    """构建角色消歧消息，仅接受标准候选结构。"""
    lines: list[str] = []

    for item in candidates:
        name = str(item["name"])
        count = int(item.get("count", 0))
        ctx = context_sentences.get(name, "") if context_sentences else ""
        evidence_profile = build_evidence_profile(ctx)
        evidence_types = _extract_evidence_types_from_context(ctx)
        evidence_annotation = _format_evidence_annotation(evidence_types)
        profile_block = _format_candidate_block(name, count, ctx, evidence_profile)
        if evidence_annotation:
            lines.append(profile_block + f"\n  {evidence_annotation}")
        else:
            lines.append(profile_block)

    body = "\n".join(lines)

    system_prompt = _build_dynamic_system_prompt()
    system_prompt += (
        "\n\n【置信度输出要求】请在 JSON 中额外输出 alias_confidence 字段，"
        "key 为候选名字，value 仅允许 low|medium|high。"
        "high 表示证据充分，medium 表示倾向如此但证据不足，low 表示无法确认。"
    )

    if existing_names:
        anchor_str = "、".join(existing_names)
        system_prompt += (
            f"\n\n【已存在的角色】以下名字已在知识库中存在：[{anchor_str}]。"
            "如果你有充分证据认为候选人名与这些角色是同一人物，可以合并；如果证据不足，保持独立。"
        )

    user_parts = [
        "以下候选人名可能是同一人物的不同称呼，也可能是不同人物。",
        "请根据例句中的上下文判断，若两人明显是不同人物请不要合并。",
    ]
    if rag_hint:
        user_parts.append(rag_hint)
    user_parts.append(f"\n候选人名列表：\n{body}")
    user_content = "\n".join(user_parts)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def build_anonymous_disambig_messages(
    anonymous_names: list[str],
    anonymous_contexts: dict[str, str],
    existing_names: list[str] | None = None,
    existing_contexts: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """构建匿名人物消歧消息。"""
    info_parts: list[str] = []
    for name in anonymous_names:
        ctx = anonymous_contexts.get(name, "无上下文")
        info_parts.append(f"【匿名人物】{name}\n上下文：\n{ctx}\n---")
    anonymous_info = "\n\n".join(info_parts)

    existing_lines: list[str] = []
    if existing_names:
        for name in existing_names:
            ctx = existing_contexts.get(name, "") if existing_contexts else ""
            if ctx:
                existing_lines.append(f"- {name}（参考：{ctx}）")
            else:
                existing_lines.append(f"- {name}")
    existing_str = "\n".join(existing_lines) if existing_lines else "无"

    user_content = f"""以下匿名占位名需要识别真实身份。

【已知常用名】
{existing_str}

{anonymous_info}

请根据上下文判断每个匿名人物的真实身份。"""

    return [
        {"role": "system", "content": ANONYMOUS_DISAMBIG_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
