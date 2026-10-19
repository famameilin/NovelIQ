"""章级声明候选关系的事务保存与核对，不发布正式事件或结构

章级声明之间的候选关系进入
event_links 的语义形状（两端都引用 event_declarations），证据进入
paragraph_evidence 的 narrative_link_id 所有者列。
"""

from src.storage.records.events import EventSave


def check_declaration_contribution(storage, frozen) -> bool:
    "保存回执核对对应执行的不可变贡献"
    return storage.narrative.check_contribution(
        EventSave(
            frozen.run_id,
            frozen.agent_id,
            frozen.chapter_order,
            frozen.paragraphs,
            frozen.snapshot_json,
            frozen.entities_json,
        )
    )
