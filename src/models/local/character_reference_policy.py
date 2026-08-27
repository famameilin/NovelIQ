"""角色引用分层准入规则"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

ReferenceKind = Literal["global_character", "pronoun", "pov_slot", "generic_reference"]

POV_SLOT_PREFIX = "POV_SLOT_"
LOCAL_REFERENCE_SLOT_PREFIX = "LOCAL_REF_"

POV_PRONOUNS: frozenset[str] = frozenset({"我", "我们", "咱", "咱们"})
PERSON_PRONOUNS: frozenset[str] = frozenset(
    {
        "你",
        "您",
        "你们",
        "他",
        "她",
        "它",
        "他们",
        "她们",
        "它们",
        "自己",
        "本人",
    }
)
GENERIC_REFERENCE_NAMES: frozenset[str] = frozenset(
    {
        "来人",
        "有人",
        "某人",
        "众人",
        "旁人",
        "那人",
        "此人",
    }
)


@dataclass(frozen=True)
class CharacterReferenceDecision:
    """创建时间: 2026-04-29 作用: 保存角色引用准入决策结果"""

    surface_name: str
    reference_kind: ReferenceKind
    reference_slot: str | None
    resolved_global_name: str | None
    can_enter_global_character: bool
    global_skip_reason: str | None


def normalize_reference_name(name: str | None) -> str:
    """创建时间: 2026-04-29 作用: 规范化角色引用名称"""
    if name is None:
        return ""
    return str(name).strip()


def classify_reference_kind(surface_name: str | None) -> ReferenceKind:
    """创建时间: 2026-04-29 作用: 区分全局角色、代词、视角位和泛指引用"""
    normalized = normalize_reference_name(surface_name)
    if normalized.startswith(POV_SLOT_PREFIX):
        return "pov_slot"
    if normalized.startswith(LOCAL_REFERENCE_SLOT_PREFIX):
        return "generic_reference"
    if normalized in POV_PRONOUNS:
        return "pov_slot"
    if normalized in PERSON_PRONOUNS:
        return "pronoun"
    if normalized in GENERIC_REFERENCE_NAMES:
        return "generic_reference"
    return "global_character"


def is_reference_slot_name(name: str | None) -> bool:
    """创建时间: 2026-04-29 作用: 判断名称是否为局部引用位"""
    normalized = normalize_reference_name(name)
    return normalized.startswith(POV_SLOT_PREFIX) or normalized.startswith(LOCAL_REFERENCE_SLOT_PREFIX)


def is_global_character_surface_name(name: str | None) -> bool:
    """创建时间: 2026-04-29 作用: 判断名称是否可直接作为全局角色名"""
    normalized = normalize_reference_name(name)
    return bool(normalized) and classify_reference_kind(normalized) == "global_character"


def build_reference_slot(surface_name: str | None, *, chunk_id: int | None = None) -> str | None:
    """创建时间: 2026-04-29 作用: 把未解析引用转换为稳定引用位"""
    normalized = normalize_reference_name(surface_name)
    if is_reference_slot_name(normalized):
        return normalized
    kind = classify_reference_kind(normalized)
    if kind == "global_character" or not normalized:
        return None
    prefix = "POV_SLOT" if kind == "pov_slot" else "LOCAL_REF"
    chunk_part = f"_C{chunk_id}" if chunk_id is not None else ""
    return f"{prefix}{chunk_part}_{normalized}"


def collect_reference_slots_from_names(
    names: Iterable[str | None],
    *,
    chunk_id: int | None = None,
) -> list[str]:
    """创建时间: 2026-04-29 作用: 从名称列表提取并去重局部引用位"""
    reference_slots: list[str] = []
    for name in names:
        slot = build_reference_slot(name, chunk_id=chunk_id)
        if slot and slot not in reference_slots:
            reference_slots.append(slot)
    return reference_slots


def resolve_global_character_name(
    surface_name: str | None,
    *,
    resolved_global_name: str | None = None,
) -> str | None:
    """创建时间: 2026-04-29 作用: 解析允许进入主链的全局角色名"""
    explicit_resolved = normalize_reference_name(resolved_global_name)
    if explicit_resolved:
        if is_global_character_surface_name(explicit_resolved):
            return explicit_resolved
        return None

    normalized = normalize_reference_name(surface_name)
    if not is_global_character_surface_name(normalized):
        return None
    return normalized


def decide_character_reference(
    surface_name: str | None,
    *,
    resolved_global_name: str | None = None,
    chunk_id: int | None = None,
) -> CharacterReferenceDecision:
    """创建时间: 2026-04-29 作用: 生成角色引用的统一准入决策"""
    normalized = normalize_reference_name(surface_name)
    reference_kind = classify_reference_kind(normalized)
    global_name = resolve_global_character_name(
        normalized,
        resolved_global_name=resolved_global_name,
    )
    can_enter = global_name is not None
    skip_reason = None
    if not can_enter:
        if not normalized:
            skip_reason = "empty surface name"
        elif reference_kind == "pov_slot":
            skip_reason = "unresolved pov reference"
        elif reference_kind == "pronoun":
            skip_reason = "unresolved pronoun reference"
        elif reference_kind == "generic_reference":
            skip_reason = "unresolved generic reference"
        else:
            skip_reason = "unresolved global character"

    return CharacterReferenceDecision(
        surface_name=normalized,
        reference_kind=reference_kind,
        reference_slot=build_reference_slot(normalized, chunk_id=chunk_id),
        resolved_global_name=global_name,
        can_enter_global_character=can_enter,
        global_skip_reason=skip_reason,
    )


def filter_global_character_names(
    names: list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> list[str]:
    """创建时间: 2026-04-29 作用: 过滤并去重可进入主链的全局角色名"""
    filtered: list[str] = []
    for name in names:
        resolved = resolve_global_character_name(name)
        if resolved and resolved not in filtered:
            filtered.append(resolved)
    return filtered
