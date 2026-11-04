"""标注角色可写域；越域写入在账本入口拒绝"""

from __future__ import annotations

# 域按生产写入工具命名；参与者随 event 写入，label 随 metrics 写入
WRITE_DOMAINS: tuple[str, ...] = (
    "entity",
    "relation",
    "event",
    "dialogue",
    "metrics",
    "queue",
    "reference",
    "retract",
    "plotline",
    "foreshadow_action",
)

ROLE_WRITE_DOMAINS: dict[str, frozenset[str]] = {
    "annotation": frozenset(WRITE_DOMAINS),
    "entity": frozenset({"entity", "relation"}),
    "event": frozenset({"event", "queue", "reference", "retract", "plotline", "foreshadow_action"}),
    "metric": frozenset({"dialogue", "metrics", "queue", "reference", "retract"}),
}
