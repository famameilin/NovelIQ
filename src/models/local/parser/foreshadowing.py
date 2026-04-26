"""
伏笔解析模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取伏笔解析相关逻辑
"""

from __future__ import annotations

from typing import Any, get_args

from ..schema import ForeshadowingConfidence, ForeshadowingResult, ForeshadowingType

_VALID_FORESHADOWING_TYPES = frozenset(get_args(ForeshadowingType))
_VALID_CONFIDENCES = frozenset(get_args(ForeshadowingConfidence))
_HOOK_LABEL = "具体钩子："
_UNRESOLVED_LABEL = "未闭合原因："
_STRONG_HOOK_KEYWORDS = (
    "异常",
    "未解释",
    "身份",
    "秘密",
    "来历",
    "用途",
    "真相",
    "规则",
    "约定",
    "誓言",
    "承诺",
    "威胁",
    "倒计时",
    "计划",
    "项目",
    "任务",
    "力量",
    "能力",
    "线索",
    "基地",
    "门",
    "邀请",
    "判断",
    "决定",
)
_UNRESOLVED_MARKERS = (
    "尚未",
    "仍未",
    "还未",
    "未被",
    "未曾",
    "没有解释",
    "没有交代",
    "没有揭示",
    "没有兑现",
    "没有回收",
    "用途未明",
    "身份未明",
    "来历未明",
    "原因未明",
    "真相未明",
    "当前只",
    "当前仍",
    "还没有",
)
_GENERIC_REJECTION_MARKERS = (
    "可能影响后续",
    "推动剧情",
    "推动后续",
    "可能推动",
    "可能出事",
    "后面可能",
    "后续可能",
    "暗示命运",
    "预示命运",
    "命运定调",
    "体现主题",
    "烘托主题",
    "主题铺垫",
    "情绪铺垫",
    "气氛铺垫",
    "创伤根源",
    "心理创伤",
)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    """
    判断文本是否命中任一关键短语。

    创建时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    新建原因: 将强伏笔语义过滤收口成显式 helper，避免 validate_foreshadowing_result 内散落硬编码判断。
    """
    return any(marker in text for marker in markers)


def _extract_reason_sections(reason: str) -> tuple[str | None, str | None]:
    """
    从 anchor_reason 中提取“具体钩子/未闭合原因”两段。

    创建时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    新建原因: Phase2 现在要求 anchor_reason 使用固定双段格式，先统一解析再做语义门槛校验。
    """
    normalized = reason.strip()
    hook_index = normalized.find(_HOOK_LABEL)
    unresolved_index = normalized.find(_UNRESOLVED_LABEL)
    if hook_index != 0 or unresolved_index <= hook_index:
        return None, None

    hook_text = normalized[len(_HOOK_LABEL) : unresolved_index].strip("；;。 \n\t")
    unresolved_text = normalized[unresolved_index + len(_UNRESOLVED_LABEL) :].strip("；;。 \n\t")
    if not hook_text or not unresolved_text:
        return None, None
    return hook_text, unresolved_text


def _has_strong_hook_reason(result: ForeshadowingResult) -> bool:
    """
    判断 anchor_reason 是否满足强伏笔的最小语义门槛。

    创建时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    新建原因: 将“高精度强伏笔”门槛沉淀为显式规则，优先拒绝主题句、命运定调和模糊未来推测。
    """
    hook_text, unresolved_text = _extract_reason_sections(result.anchor_reason)
    if hook_text is None or unresolved_text is None:
        return False

    if _contains_any(result.anchor_reason, _GENERIC_REJECTION_MARKERS):
        return False

    if not _contains_any(hook_text, _STRONG_HOOK_KEYWORDS):
        return False

    if not _contains_any(unresolved_text, _UNRESOLVED_MARKERS):
        return False

    return True


def parse_foreshadowing_result(data: dict[str, Any]) -> ForeshadowingResult:
    """
    解析伏笔分析结果

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    修改内容: 伏笔类型枚举改为当前中文合同，不再兼容历史 causal/thematic 残留。
    """
    has_foreshadowing = data.get("has_foreshadowing", False)

    foreshadowing_type_raw = data.get("foreshadowing_type")
    if has_foreshadowing and foreshadowing_type_raw in _VALID_FORESHADOWING_TYPES:
        foreshadowing_type: ForeshadowingType | None = foreshadowing_type_raw
    else:
        foreshadowing_type = None

    confidence_raw = data.get("confidence", "high")
    confidence: ForeshadowingConfidence = confidence_raw if confidence_raw in _VALID_CONFIDENCES else "high"

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

    修改时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    修改内容:
    - 只有 high 级 positive 才允许入强伏笔池
    - anchor_reason 必须同时给出“具体钩子/未闭合原因”
    - 显式拦截主题句、命运定调、情绪气氛类模糊推断

    返回 False 则丢弃该条记录，不入库。
    """
    if not result.has_foreshadowing:
        return True

    if result.confidence != "high":
        return False

    if not result.anchor_text or len(result.anchor_text.strip()) < 5:
        return False

    if result.anchor_text not in chunk_text:
        return False

    return _has_strong_hook_reason(result)
