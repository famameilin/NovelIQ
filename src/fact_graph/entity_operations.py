"""富登记操作的字段与来源语义，不推断描述或标签的业务真假"""

from typing import Any

#: 实体登记的显式字段（自由属性已随 3NF 合同取消；代表标记与简介是类型化字段）
ENTITY_UPDATE_FIELDS = frozenset({"tags", "description", "representative"})


def operation_fields(operation: dict[str, Any]) -> set[str]:
    """无字段掩码代表整条富登记；部分更新只作用于显式提交的字段"""
    return set(operation.get("fields", ENTITY_UPDATE_FIELDS))


def apply_entity_information(
    current: dict[str, Any],
    operation: dict[str, Any],
    tag_sources: dict[tuple[int, str], dict[str, list[str]]],
    *,
    chapter_id: int,
    identity: str,
    author: str,
) -> None:
    """同作者标签更新替换自身来源，章内跨作者标签取并集；description 与代表标记为显式字段"""
    fields = operation_fields(operation)
    if "tags" in fields:
        sources = tag_sources.setdefault((chapter_id, identity), {})
        sources[author] = list(operation["tags"])
        current["tags"] = list(dict.fromkeys(tag for source in sorted(sources) for tag in sources[source]))
    if "description" in fields and operation.get("description") is not None:
        current["attributes"] = {
            **dict(current.get("attributes", {})),
            "description": operation["description"],
        }
    if "representative" in fields:
        representative = operation.get("representative")
        if representative is not None:
            attributes = dict(current.get("attributes", {}))
            if representative:
                attributes["is_representative"] = True
            else:
                attributes.pop("is_representative", None)
            current["attributes"] = attributes
