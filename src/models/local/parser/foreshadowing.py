"""
伏笔解析模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取伏笔解析相关逻辑
"""

from __future__ import annotations

from typing import Any, get_args

from ..schema import ForeshadowingConfidence, ForeshadowingResult, ForeshadowingSetupKind, ForeshadowingType

_VALID_FORESHADOWING_TYPES = frozenset(get_args(ForeshadowingType))
_VALID_CONFIDENCES = frozenset(get_args(ForeshadowingConfidence))
_VALID_SETUP_KINDS = frozenset(get_args(ForeshadowingSetupKind))
_HOOK_LABEL = "具体钩子："
_UNRESOLVED_LABEL = "未闭合原因："
_ANOMALY_HOOK_MARKERS = (
    "异常",
    "异样",
    "异象",
    "反常",
    "诡异",
    "古怪",
    "不对劲",
    "不寻常",
    "非普通",
    "不是普通",
    "自行",
    "发热",
    "红光",
    "注视感",
    "纹样",
    "印记",
)
_STRONG_SETUP_TARGET_MARKERS = (
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
    "时限",
    "期限",
    "能力",
    "力量",
    "线索",
    "密码",
    "邀请",
    "后果",
    "代价",
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
    "用途不明",
    "去向不明",
)
_GENERIC_HOOK_REJECTION_MARKERS = (
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
_GENERIC_FUTURE_SPECULATION_MARKERS = (
    "可能影响后续",
    "推动剧情",
    "推动后续",
    "可能推动",
    "可能出事",
    "后面可能",
    "后续可能",
    "后文可能",
    "暗示后面有事",
    "预示命运不好",
)
_SETUP_KIND_HOOK_MARKERS: dict[str, tuple[str, ...]] = {
    "异常物件": _ANOMALY_HOOK_MARKERS,
    "异常规则": ("规则", "禁忌", "条件", "代价", "限制"),
    "隐藏身份": ("身份", "来历", "身世", "真相"),
    "明确承诺": ("承诺", "约定", "发誓", "立誓", "答应", "保证"),
    "明确威胁": ("威胁", "若不", "否则", "下场", "后果", "偿命", "灭门"),
    "倒计时": ("倒计时", "时限", "期限", "限期"),
    "未解释能力": ("能力", "力量", "术法", "本领"),
    "因果引线": ("原因", "线索", "真相", "力量", "代价", "后果"),
}


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


def _has_concrete_setup_signal(hook_text: str, unresolved_text: str) -> bool:
    """
    判断理由里是否真的出现了强 setup 所需的具体信号。

    创建时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    新建原因: 把“异常物件/隐藏信息/承诺威胁”等有效信号单独收口，
    避免仅凭“决定/判断尚未执行”这种日常动作误入强伏笔池。
    """
    combined = f"{hook_text} {unresolved_text}"
    return _contains_any(hook_text, _ANOMALY_HOOK_MARKERS) or _contains_any(combined, _STRONG_SETUP_TARGET_MARKERS)


def _has_setup_kind_consistent_signal(setup_kind: str, hook_text: str, unresolved_text: str) -> bool:
    """
    判断 setup_kind 是否得到了文本理由里的具体信号支撑。

    创建时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    新建原因: setup_kind 只能作为“收紧语义范围”的提示，不能替代对 hook/unresolved 文本本身的校验。
    """
    if setup_kind == "其他":
        return _has_concrete_setup_signal(hook_text, unresolved_text)

    combined = f"{hook_text} {unresolved_text}"
    markers = _SETUP_KIND_HOOK_MARKERS.get(setup_kind, ())
    if markers and _contains_any(combined, markers):
        return True

    # 中文注释：模型就算挑了正式 setup_kind，也仍然要回到文本理由里确认
    # “具体钩子到底是什么”；否则普通决定被误标成“明确承诺”时会直接绕过强伏笔 gate。
    return _has_concrete_setup_signal(hook_text, unresolved_text)


def _is_generic_future_speculation(text: str) -> bool:
    """
    判断文本是否只是泛化的未来推测。

    创建时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    新建原因: “后续可能如何”只有在同时点明具体未闭合对象时才可接受，
    不能再把所有带 future wording 的解释一刀切拒掉。
    """
    return _contains_any(text, _GENERIC_FUTURE_SPECULATION_MARKERS) and not _contains_any(
        text,
        _STRONG_SETUP_TARGET_MARKERS,
    )


def _has_strong_hook_reason(result: ForeshadowingResult) -> bool:
    """
    判断 anchor_reason 是否满足强伏笔的最小语义门槛。

    创建时间: 2026-04-26
    任务: phase2-strong-foreshadowing
    新建原因: 将“高精度强伏笔”门槛沉淀为显式规则，优先拒绝主题句、命运定调和模糊未来推测。
    """
    hook_text, anchor_unresolved_text = _extract_reason_sections(result.anchor_reason)
    if hook_text is None or anchor_unresolved_text is None:
        return False

    if _contains_any(hook_text, _GENERIC_HOOK_REJECTION_MARKERS):
        return False

    if _contains_any(anchor_unresolved_text, _GENERIC_HOOK_REJECTION_MARKERS):
        return False

    unresolved_text = result.why_unresolved_now.strip()
    if not unresolved_text:
        return False

    if _contains_any(unresolved_text, _GENERIC_HOOK_REJECTION_MARKERS):
        return False

    if not _contains_any(unresolved_text, _UNRESOLVED_MARKERS):
        return False

    # 中文注释：允许“后续可能揭示用途”这类带 future wording 的表述，
    # 前提是它确实指向了具体的未闭合对象；纯“可能有影响/可能出事”仍然拒绝。
    if _is_generic_future_speculation(hook_text):
        return False

    if _is_generic_future_speculation(anchor_unresolved_text):
        return False

    if _is_generic_future_speculation(unresolved_text):
        return False

    merged_unresolved_text = f"{anchor_unresolved_text} {unresolved_text}".strip()
    return _has_setup_kind_consistent_signal(result.setup_kind or "其他", hook_text, merged_unresolved_text)


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
    is_strong_setup = bool(data.get("is_strong_setup", False)) if has_foreshadowing else False

    foreshadowing_type_raw = data.get("foreshadowing_type")
    if has_foreshadowing and foreshadowing_type_raw in _VALID_FORESHADOWING_TYPES:
        foreshadowing_type: ForeshadowingType | None = foreshadowing_type_raw
    else:
        foreshadowing_type = None

    setup_kind_raw = data.get("setup_kind")
    if has_foreshadowing and setup_kind_raw in _VALID_SETUP_KINDS:
        setup_kind: ForeshadowingSetupKind | None = setup_kind_raw
    else:
        setup_kind = None

    confidence_raw = data.get("confidence", "high")
    confidence: ForeshadowingConfidence = confidence_raw if confidence_raw in _VALID_CONFIDENCES else "low"

    return ForeshadowingResult(
        has_foreshadowing=has_foreshadowing,
        is_strong_setup=is_strong_setup,
        foreshadowing_type=foreshadowing_type,
        setup_kind=setup_kind,
        anchor_text=data.get("anchor_text", ""),
        anchor_reason=data.get("anchor_reason", ""),
        why_unresolved_now=data.get("why_unresolved_now", "") if has_foreshadowing else "",
        expected_payoff_family=data.get("expected_payoff_family", "") if has_foreshadowing else "",
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
    - `has_foreshadowing=false` 时也要拒绝夹带 strong setup 字段的脏 negative
    - 只有 high 级 positive 才允许入强伏笔池
    - positive 结果必须携带正式 foreshadowing_type
    - positive 结果必须补齐结构化语义字段，减少仅凭 anchor_reason 猜意图
    - anchor_reason 必须同时给出“具体钩子/未闭合原因”
    - 显式拦截主题句、命运定调、情绪气氛类模糊推断

    返回 False 则丢弃该条记录，不入库。
    """
    if not result.has_foreshadowing:
        if result.is_strong_setup:
            return False
        if result.foreshadowing_type is not None:
            return False
        if result.setup_kind is not None:
            return False
        if result.why_unresolved_now.strip():
            return False
        if result.expected_payoff_family.strip():
            return False
        return True

    if not result.is_strong_setup:
        return False

    if result.confidence != "high":
        return False

    if result.foreshadowing_type is None:
        return False

    if result.setup_kind is None:
        return False

    if not result.anchor_text or len(result.anchor_text.strip()) < 5:
        return False

    if result.anchor_text not in chunk_text:
        return False

    if not result.why_unresolved_now or len(result.why_unresolved_now.strip()) < 6:
        return False

    if not result.expected_payoff_family or len(result.expected_payoff_family.strip()) < 2:
        return False

    return _has_strong_hook_reason(result)
