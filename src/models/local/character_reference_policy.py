"""角色引用分层准入规则。

说明: 该模块是 annotation / disambiguation / graph / results / diagnosis
共用的角色主链准入入口，避免各模块继续把原文称呼直接当成全局角色。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

ReferenceKind = Literal["global_character", "pronoun", "pov_slot", "generic_reference"]

REFERENCE_CONTRACT_VERSION = 1
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
BLOCKED_SURFACE_REFERENCES: frozenset[str] = POV_PRONOUNS | PERSON_PRONOUNS | GENERIC_REFERENCE_NAMES


@dataclass(frozen=True)
class CharacterReferenceDecision:
    """角色引用准入决策结果。"""

    surface_name: str
    reference_kind: ReferenceKind
    reference_slot: str | None
    resolved_global_name: str | None
    can_enter_global_character: bool
    global_skip_reason: str | None


def normalize_reference_name(name: str | None) -> str:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 所有角色引用入口需要统一去空白，避免各模块自行判断空串。
    """
    if name is None:
        return ""
    return str(name).strip()


def classify_reference_kind(surface_name: str | None) -> ReferenceKind:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 统一区分原文称呼、视角位和可进入主链的全局角色。
    """
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
    """
    创建时间: 2026-04-29
    任务: Phase4 / RAG reference_slots 合同
    新建原因: Phase4 prompt、RAG request 与读侧过滤都需要显式识别 slot 前缀，避免把 slot 当成全局角色名。
    """
    normalized = normalize_reference_name(name)
    return normalized.startswith(POV_SLOT_PREFIX) or normalized.startswith(LOCAL_REFERENCE_SLOT_PREFIX)


def is_reference_surface_name(name: str | None) -> bool:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 消歧与图谱投影需要快速判断一个 surface 是否只能作为局部引用。
    """
    return classify_reference_kind(name) != "global_character"


def is_global_character_surface_name(name: str | None) -> bool:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: results/diagnosis/graph 需要共用“可直接作为全局角色名”的判断。
    """
    normalized = normalize_reference_name(name)
    return bool(normalized) and classify_reference_kind(normalized) == "global_character"


def build_reference_slot(surface_name: str | None, *, chunk_id: int | None = None) -> str | None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 未解析代词需要保留为稳定 reference slot，而不是被提升为 canonical。
    """
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
    """
    创建时间: 2026-04-29
    任务: Phase4 / RAG reference_slots 合同
    新建原因: Phase4 request 需要把局部引用位从 global names 中分离出来，并保留稳定的 slot 列表。
    """
    reference_slots: list[str] = []
    for name in names:
        slot = build_reference_slot(name, chunk_id=chunk_id)
        if slot and slot not in reference_slots:
            reference_slots.append(slot)
    return reference_slots


def collect_reference_slots_from_text(
    text: str | None,
    *,
    chunk_id: int | None = None,
) -> list[str]:
    """
    创建时间: 2026-04-29
    任务: Phase4 / RAG reference_slots 合同
    新建原因: context.py 在 Phase4 request template 阶段还拿不到 Phase1 结果，需要先从当前 chunk 识别局部引用位。
    """
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return []

    surface_pattern = "|".join(
        re.escape(surface_name)
        for surface_name in sorted(BLOCKED_SURFACE_REFERENCES, key=len, reverse=True)
    )
    if not surface_pattern:
        return []

    matched_surfaces = [match.group(0) for match in re.finditer(surface_pattern, normalized_text)]
    return collect_reference_slots_from_names(matched_surfaces, chunk_id=chunk_id)


def resolve_global_character_name(
    surface_name: str | None,
    *,
    alias_map: dict[str, str] | None = None,
    resolved_global_name: str | None = None,
) -> str | None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 已解析代词只能以实名进入主链，未解析 surface 不能自行升级。
    """
    explicit_resolved = normalize_reference_name(resolved_global_name)
    if explicit_resolved:
        if is_global_character_surface_name(explicit_resolved):
            mapped_name = alias_map.get(explicit_resolved, explicit_resolved) if alias_map else explicit_resolved
            return mapped_name if is_global_character_surface_name(mapped_name) else None
        return None

    normalized = normalize_reference_name(surface_name)
    if not is_global_character_surface_name(normalized):
        return None
    mapped_name = alias_map.get(normalized, normalized) if alias_map else normalized
    return mapped_name if is_global_character_surface_name(mapped_name) else None


def decide_character_reference(
    surface_name: str | None,
    *,
    alias_map: dict[str, str] | None = None,
    resolved_global_name: str | None = None,
    chunk_id: int | None = None,
) -> CharacterReferenceDecision:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 将“surface -> reference_kind -> resolved_global_name -> can_enter”收口为单一决策对象。
    """
    normalized = normalize_reference_name(surface_name)
    reference_kind = classify_reference_kind(normalized)
    global_name = resolve_global_character_name(
        normalized,
        alias_map=alias_map,
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
    *,
    alias_map: dict[str, str] | None = None,
) -> list[str]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: Phase3/Phase4/results/diagnosis 需要用同一规则过滤主链角色名单。
    """
    filtered: list[str] = []
    for name in names:
        resolved = resolve_global_character_name(name, alias_map=alias_map)
        if resolved and resolved not in filtered:
            filtered.append(resolved)
    return filtered
