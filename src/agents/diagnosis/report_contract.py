"""报告写入面的角色规范化与交叉校验"""

from __future__ import annotations

from typing import Any

from src.diagnosis.normalization import normalize_character_key
from src.diagnosis.schema import AgentAnalysisSubmission


def validate_report_write(
    analysis: AgentAnalysisSubmission,
    *,
    roster: dict[str, str],
    topic_ids: set[int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """规范化角色名并校验名单、焦点结构与主题键；返回落库载荷与回执附加信息"""
    renamed: dict[str, str] = {}

    def canonical(name: str) -> str:
        resolved = roster.get(normalize_character_key(name))
        if resolved is None:
            raise ValueError(f"以下名字不是本 run 的正式角色: {name}")
        if name != resolved:
            renamed[name] = resolved
        return resolved

    payload = analysis.model_dump(mode="json")
    payload["arc_scores"] = {canonical(name): score for name, score in analysis.arc_scores.items()}
    for field in ("focus_characters", "main_characters", "core_cast"):
        payload[field] = [canonical(name) for name in getattr(analysis, field)]
    if len(payload["main_characters"]) > 5:
        raise ValueError("main_characters 最多 5 个")
    arc_names = set(payload["arc_scores"])
    for field in ("focus_characters", "main_characters", "core_cast"):
        missing = [name for name in payload[field] if name not in arc_names]
        if missing:
            raise ValueError(f"{field} 中的人物必须同时出现在 arc_scores: {missing}")
    focus = payload["focus_characters"]
    structure = payload.get("focus_structure")
    derived: dict[str, Any] = {}
    if focus:
        expected = "single" if len(focus) == 1 else "dual" if len(focus) == 2 else "ensemble"
        if structure is None:
            payload["focus_structure"] = expected
            derived["focus_structure"] = expected
        elif structure != expected:
            raise ValueError(f"focus_structure={structure} 与焦点人物数量 {len(focus)} 不一致（应为 {expected}）")
    elif structure is not None:
        raise ValueError("focus_characters 为空时不要提交 focus_structure")
    try:
        actual = {int(key) for key in payload["topic_labels"]}
    except (TypeError, ValueError) as exc:
        raise ValueError(f"topic_labels 的键必须是真实主题数字 ID: {list(payload['topic_labels'])}") from exc
    missing_topics = sorted(topic_ids - actual)
    extra_topics = sorted(actual - topic_ids)
    if missing_topics or extra_topics:
        raise ValueError(f"topic_labels 必须与真实主题 ID 完全一致；缺少 {missing_topics}，多出 {extra_topics}")
    details: dict[str, Any] = {"topic_gap": 0}
    if renamed:
        details["canonicalized"] = renamed
    if derived:
        details["derived"] = derived
    return payload, details
