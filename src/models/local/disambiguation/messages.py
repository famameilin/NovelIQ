"""消歧消息构建模块。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.config import settings
from src.config.constants import VALID_ENTITY_TYPES
from src.models.disambiguation_types import NameCountCandidate

from ..prompts import (
    ANONYMOUS_DISAMBIG_SYSTEM_PROMPT,
    CANONICAL_RESELECT_SYSTEM_PROMPT,
    DISAMBIGUATE_SYSTEM_PROMPT,
)
from .constants import PROTECTED_CATEGORY_LABEL
from .evidence import build_evidence_profile, format_evidence_profile
from .evidence_renderer import DisambiguationPromptContext, render_disambiguation_prompt_context_sections

if TYPE_CHECKING:
    from src.workflows.annotate_helpers.disambiguation.candidate_filter import CandidateClassification

    from .evidence import EvidenceProfile
    from .state import NameReviewState

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

_EVIDENCE_MARKER_PATTERN = re.compile(
    r"【(前文总结|自报身份|身份提示|被点名|外貌描写|独特标记|亲缘身份|命名场景|身份线索)】"
)
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


def _get_category_label(category: str | None) -> str:
    """将分类类别转为中文标签。"""
    if category == "protected":
        return PROTECTED_CATEGORY_LABEL
    return "普通"


def _format_candidate_block(
    name: str,
    count: int,
    context: str,
    evidence_profile: EvidenceProfile,
    category: str | None = None,
) -> str:
    """构建更结构化的候选项描述。"""

    lines = [
        f"- 候选称呼：{name}",
        f"  次数：{count}",
    ]
    if category and category != "normal":
        lines.append(f"  类别：{_get_category_label(category)}")
    lines.append(f"  {format_evidence_profile(evidence_profile)}")
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
    "group": (
        "特定几人的并称/合称（如侠义七子、中原五侠、江南七怪），"
        "指向明确的个体集合；泛指类别（如蛊仙、修士、凡人）不算 group"
    ),
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
    valid_types = list(VALID_ENTITY_TYPES) or ["character"]
    lines = ["【实体类型识别规则】"]
    for etype in valid_types:
        desc = _ENTITY_TYPE_DESCRIPTIONS.get(etype, f"{etype} 类型")
        lines.append(f"- {etype}：{desc}")
    return "\n".join(lines)


def _build_entity_types_union() -> str:
    """构建实体类型联合字符串，用于 JSON 格式说明。"""
    valid_types = list(VALID_ENTITY_TYPES) or ["character"]
    return "|".join(valid_types)


def _build_dynamic_system_prompt() -> str:
    """将动态关系类型和实体类型填入系统提示词模板。"""
    base_prompt = DISAMBIGUATE_SYSTEM_PROMPT
    base_prompt = base_prompt.replace("{{RELATION_TYPES_UNION}}", _build_relation_types_union())
    base_prompt = base_prompt.replace("{{RELATION_TYPES_SECTION}}", _build_relation_types_section())
    base_prompt = base_prompt.replace("{{ENTITY_TYPES_UNION}}", _build_entity_types_union())
    base_prompt = base_prompt.replace("{{ENTITY_TYPES_SECTION}}", _build_entity_types_section())
    return base_prompt


def _format_reselect_review_summary(review: NameReviewState | None) -> list[str]:
    """
    格式化最终代表名重选阶段的复审摘要。

    创建时间: 2026-04-22
    创建者: Codex
    任务: final-canonical-reselect
    说明: 终消歧后的额外重选不再判断“是不是同一人”，而是只在已确认 cluster 内
          选择代表名；这里把当前状态机里已有的复审审计字段整理成稳定提示，供模型参考。
    """
    if review is None:
        return ["  当前复审：无"]

    evidence_types = "、".join(review.decision_evidence_types) if review.decision_evidence_types else "无"
    return [
        f"  当前复审：{review.status} / {review.confidence}",
        f"  当前锚点：{review.proposed_canonical or '无'}",
        f"  证据强度：{review.evidence_strength or '无'}",
        f"  审计证据：{evidence_types}",
    ]


def build_disambiguate_messages(
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str] | None = None,
    existing_names: list[str] | None = None,
    prompt_context: DisambiguationPromptContext | None = None,
    classifications: list[CandidateClassification] | None = None,
) -> list[dict[str, str]]:
    """
    构建角色消歧消息，仅接受标准候选结构。

    修改时间: 2026-04-24
    任务: unify-disambig-transport-record-arrays
    修改内容: 消歧提示词统一为记录数组格式，与传输层响应模型保持一致。
    """
    # Build name -> category lookup
    category_map: dict[str, str] = {}
    if classifications:
        for cls in classifications:
            category_map[cls.name] = cls.category

    lines: list[str] = []

    for item in candidates:
        name = str(item["name"])
        count = int(item.get("count", 0))
        ctx = context_sentences.get(name, "") if context_sentences else ""
        evidence_profile = build_evidence_profile(ctx)
        evidence_types = _extract_evidence_types_from_context(ctx)
        evidence_annotation = _format_evidence_annotation(evidence_types)
        category = category_map.get(name)
        profile_block = _format_candidate_block(name, count, ctx, evidence_profile, category)
        if evidence_annotation:
            lines.append(profile_block + f"\n  {evidence_annotation}")
        else:
            lines.append(profile_block)

    body = "\n".join(lines)

    system_prompt = _build_dynamic_system_prompt()
    system_prompt += (
        "\n\n【置信度输出要求】请在 JSON 中额外输出 alias_confidence 字段，"
        "使用记录数组格式，每条记录必须包含 name 与 confidence 字段，confidence 仅允许 low|medium|high。"
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
    user_parts.extend(render_disambiguation_prompt_context_sections(prompt_context))
    user_parts.append(f"\n候选人名列表：\n{body}")
    user_content = "\n".join(user_parts)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def build_canonical_reselect_messages(
    candidates: list[NameCountCandidate],
    clusters: list[list[str]],
    context_sentences: dict[str, str] | None = None,
    review_states: dict[str, NameReviewState] | None = None,
) -> list[dict[str, str]]:
    """
    构建最终代表名重选消息。

    创建时间: 2026-04-22
    创建者: Codex
    任务: final-canonical-reselect
    说明: 该阶段只负责“在已确认同一人的 cluster 内选最终代表名”，
          因此 prompt 明确按组组织输入，禁止模型重新拆组或跨组合并。

    修改时间: 2026-04-24
    任务: unify-disambig-transport-record-arrays
    修改内容: 重选提示词统一为记录数组格式，与传输层响应模型保持一致。
    """
    counts_by_name = {str(candidate["name"]): int(candidate.get("count", 0)) for candidate in candidates}
    cluster_blocks: list[str] = []

    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster_lines = [f"【角色组{cluster_index}】", "已确认同一人： " + " / ".join(cluster)]
        for name in cluster:
            cluster_lines.append(f"- 名字：{name}")
            cluster_lines.append(f"  次数：{counts_by_name.get(name, 0)}")
            cluster_lines.extend(_format_reselect_review_summary((review_states or {}).get(name)))
            context = (context_sentences or {}).get(name, "").strip()
            if context:
                cluster_lines.append(f"  参考上下文：{context}")
        cluster_blocks.append("\n".join(cluster_lines))

    user_content = "以下每组名字都已经确认是同一人物，请只在组内选择最终代表名。\n\n" + "\n\n".join(cluster_blocks)

    return [
        {"role": "system", "content": CANONICAL_RESELECT_SYSTEM_PROMPT},
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
