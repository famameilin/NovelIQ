"""章级声明候选关系的事务保存与核对，不发布正式事件或结构

章级声明之间的候选关系进入
narrative_links 的语义形状（两端都引用 event_declarations），证据进入
source_evidence 的 narrative_link_id 所有者列。
"""

from src.storage.records.events import EventSave


def check_declaration_contribution(storage, frozen) -> bool:
    """保存回执核对不可变贡献，后续合法版本不会使先前 work 的保存回执失效"""
    return storage.narrative.check_contribution(
        EventSave(
            frozen.run_id,
            frozen.execution_id,
            frozen.chapter_order,
            frozen.paragraphs,
            frozen.snapshot_json,
            frozen.entities_json,
        )
    )
