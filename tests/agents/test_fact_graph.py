"""章节 Agent 常驻事实图状态测试"""

from __future__ import annotations

import pytest

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import RelationInput


def _relation(
    from_entity: str,
    to_entity: str,
    relation_type: str,
) -> RelationInput:
    """2026-08-12 用于构造三字段关系边输入（本章确认存在的边）"""
    return RelationInput(
        from_entity=from_entity,
        to_entity=to_entity,
        relation_type=relation_type,
    )


class _Entity:
    """2026-08-09 用于构造测试实体目录项"""

    def __init__(self, name: str, entity_type: str) -> None:
        self.name = name
        self.entity_type = entity_type


def test_fact_graph_registers_entities_and_applies_assert() -> None:
    """2026-08-09 用于验证实体注册与 assert 新边即时生效"""
    graph = FactGraph()
    graph.register_entities([_Entity("贺伯安", "character"), _Entity("猴子", "character")])
    assert graph.entity_type("贺伯安") == "character"
    assert graph.apply_relation(_relation("贺伯安", "猴子", "友情")) is True
    assert graph.relation_exists("贺伯安", "猴子", "友情")
    assert graph.relation_exists("猴子", "贺伯安", "友情")


def test_fact_graph_existing_edge_is_noop_not_reinforce() -> None:
    """2026-08-12 用于验证已存在边的再次提交是 skipped_existing，不累计支持度"""
    graph = FactGraph()
    graph.register_entities([_Entity("算盘", "character"), _Entity("猴子", "character")])
    assert graph.apply_relation(_relation("算盘", "猴子", "友情")) is True
    assert graph.apply_relation(_relation("算盘", "猴子", "友情")) is False
    assert graph.relation_exists("算盘", "猴子", "友情")
    assert list(graph.relation_attributes.values())[0]["support_count"] == 1


def test_fact_graph_loads_history_relations() -> None:
    """2026-08-09 用于验证历史关系加载；已存在边再次提交为 no-op"""
    graph = FactGraph(
        history_entity_types={"贺伯安": "character", "赵兰英": "character"},
        history_entity_names={"贺伯安": "贺伯安", "赵兰英": "赵兰英"},
        history_relations={("贺伯安", "赵兰英", "家族")},
    )
    assert graph.relation_exists("赵兰英", "贺伯安", "家族")
    assert graph.apply_relation(_relation("贺伯安", "赵兰英", "家族")) is False


def test_fact_graph_entity_registration_appends_and_keeps_previous() -> None:
    """2026-08-09 创建；2026-08-23 用于验证实体注册为追加语义，已注册实体不被后续调用撤销"""
    graph = FactGraph()
    graph.register_entities([_Entity("算盘", "character")])
    assert graph.entity_type("算盘") == "character"
    graph.register_entities([_Entity("猴子", "character")])
    assert graph.entity_type("算盘") == "character"
    assert graph.entity_type("猴子") == "character"


def test_fact_graph_snapshot_restore_rolls_back_chapter_changes() -> None:
    """2026-08-09 用于验证章节尝试失败恢复历史快照"""
    graph = FactGraph(
        history_entity_types={"贺伯安": "character"},
        history_entity_names={"贺伯安": "贺伯安"},
    )
    baseline = graph.snapshot()
    graph.register_entities([_Entity("算盘", "character")])
    graph.apply_relation(_relation("算盘", "贺伯安", "友情"))
    graph.restore(baseline)
    assert graph.entity_type("算盘") is None
    assert not graph.relation_exists("算盘", "贺伯安", "友情")
    assert graph.entity_type("贺伯安") == "character"


def test_fact_graph_rejects_registered_type_change() -> None:
    """2026-08-09 用于验证已登记实体不允许变更大类"""
    graph = FactGraph(history_entity_types={"贺伯安": "character"})
    with pytest.raises(ValueError, match="已登记实体不允许变更大类"):
        graph.register_entities([_Entity("贺伯安", "item")])


def test_begin_chapter_keeps_previous_chapter_edges_and_clears_tracking() -> None:
    """2026-08-11 用于验证章节边界把本章增量并入历史，不删除上一章 assert 的关系"""
    graph = FactGraph()
    graph.register_entities([_Entity("算盘", "character"), _Entity("猴子", "character")])
    graph.apply_relation(_relation("算盘", "猴子", "友情"))
    assert graph.relation_exists("算盘", "猴子", "友情")

    graph.begin_chapter()

    assert graph.relation_exists("算盘", "猴子", "友情")
    graph.apply_relation(_relation("算盘", "猴子", "友情"))
    assert graph.relation_exists("算盘", "猴子", "友情")


def test_reset_chapter_relations_after_begin_chapter_keeps_previous_chapter_edges() -> None:
    """2026-08-11 用于复现跨章污染：上一章 assert 的边不得被本章 reset 误删"""
    graph = FactGraph()
    graph.register_entities([_Entity("算盘", "character"), _Entity("猴子", "character")])
    graph.apply_relation(_relation("算盘", "猴子", "友情"))
    graph.begin_chapter()
    graph.register_entities([_Entity("顾霜", "character")])

    graph.reset_chapter_relations()
    graph.apply_relation(_relation("顾霜", "猴子", "盟友"))

    assert graph.relation_exists("算盘", "猴子", "友情")
    assert graph.relation_exists("顾霜", "猴子", "盟友")


def test_reset_chapter_changes_after_begin_chapter_keeps_previous_chapter_state() -> None:
    """2026-08-13 P1-1 用于验证失败回滚恢复到上一章结束快照而非 run 启动快照

    begin_chapter 把本章增量并入 history_*，reset_chapter_changes 回滚时
    上一章登记的实体与 assert 的边保留，仅撤销本章增量。
    """
    graph = FactGraph()
    graph.register_entities([_Entity("算盘", "character")])
    graph.apply_relation(_relation("算盘", "猴子", "友情"))
    graph.begin_chapter()

    graph.register_entities([_Entity("顾霜", "character")])
    graph.reset_chapter_changes()

    assert graph.entity_type("算盘") == "character"
    assert graph.relation_exists("算盘", "猴子", "友情")
    assert graph.entity_type("顾霜") is None


def test_begin_chapter_clears_chapter_registered_entities_only() -> None:
    """2026-08-11 用于验证章节边界只撤销本章登记实体，上一章登记的实体保留"""
    graph = FactGraph()
    graph.register_entities([_Entity("算盘", "character")])
    graph.begin_chapter()

    graph.register_entities([_Entity("猴子", "character")])

    assert graph.entity_type("算盘") == "character"
    assert graph.entity_type("猴子") == "character"


class _RichEntity(_Entity):
    """2026-08-11 用于构造带标签、简介和属性补丁的实体目录项"""

    def __init__(
        self,
        name: str,
        entity_type: str,
        *,
        tags: list[str] | None = None,
        description: str | None = None,
        attributes: dict | None = None,
    ) -> None:
        super().__init__(name, entity_type)
        self.tags = tags or []
        self.description = description
        self.attributes = attributes or {}


def test_fact_graph_loads_history_properties_and_relation_attributes() -> None:
    """2026-08-11 用于验证初始加载携带实体属性与关系属性供运行时查询"""
    graph = FactGraph(
        history_entity_types={"贺伯安": "character"},
        history_entity_names={"贺伯安": "贺伯安"},
        history_entity_tags={"贺伯安": ["主角"]},
        history_entity_attributes={"贺伯安": {"entity_type": "character", "description": "男主"}},
        history_entity_state={"贺伯安": {"status": "active"}},
        history_relations={("贺伯安", "赵兰英", "家族")},
        history_relation_attributes={("贺伯安", "赵兰英", "家族"): {"support_count": 2}},
    )
    assert graph.entity_tags["贺伯安"] == ["主角"]
    assert graph.entity_attributes["贺伯安"]["description"] == "男主"
    assert graph.entity_state["贺伯安"] == {"status": "active"}
    assert graph.relation_attributes[("贺伯安", "赵兰英", "家族")] == {"support_count": 2}


def test_fact_graph_apply_relation_maintains_relation_attributes() -> None:
    """2026-08-12 用于验证新边 assert 累计支持度，已存在边 no-op 不重复累计"""
    graph = FactGraph()
    graph.apply_relation(_relation("顾霜", "顾老", "同一人物"))
    key = ("顾老", "顾霜", "同一人物")
    assert graph.relation_attributes[key]["support_count"] == 1

    graph.apply_relation(_relation("顾霜", "顾老", "同一人物"))
    assert graph.relation_attributes[key]["support_count"] == 1


def test_reset_chapter_relations_rolls_back_support_count() -> None:
    """2026-08-13 P2-9 write_relations 完整替换：reset 回退本章新增边的 support_count，
    重新提交已 assert 边不重复 +1（修复前每次替换 +1 导致支持度虚高）"""
    graph = FactGraph()
    graph.register_entities([_Entity("顾霜", "character"), _Entity("顾老", "character")])
    graph.apply_relation(_relation("顾霜", "顾老", "同一人物"))
    key = ("顾老", "顾霜", "同一人物")
    assert graph.relation_attributes[key]["support_count"] == 1

    # 同一章节内第二次 write_relations 完整替换：先 reset 再重新 apply 同一条边
    graph.reset_chapter_relations()
    assert key not in graph.relation_attributes
    assert not graph.relation_exists("顾霜", "顾老", "同一人物")

    graph.apply_relation(_relation("顾霜", "顾老", "同一人物"))

    assert graph.relation_attributes[key]["support_count"] == 1


def test_reset_chapter_relations_rolls_back_support_count_only_for_chapter_edges() -> None:
    """2026-08-13 P2-9 reset 只回退本章新增边的计数，历史边的 support_count 不受影响"""
    graph = FactGraph(
        history_entity_types={"贺伯安": "character", "赵兰英": "character"},
        history_entity_names={"贺伯安": "贺伯安", "赵兰英": "赵兰英"},
        history_relations={("贺伯安", "赵兰英", "家族")},
        history_relation_attributes={("贺伯安", "赵兰英", "家族"): {"support_count": 2}},
    )
    graph.register_entities([_Entity("顾霜", "character")])
    graph.apply_relation(_relation("顾霜", "贺伯安", "友情"))
    graph.reset_chapter_relations()

    assert graph.relation_attributes[("贺伯安", "赵兰英", "家族")] == {"support_count": 2}
    assert graph.relation_exists("贺伯安", "赵兰英", "家族")


def test_fact_graph_register_entities_updates_tags_and_description() -> None:
    """2026-08-11 用于验证当章登记实体携带标签与简介属性"""
    graph = FactGraph()
    graph.register_entities([_RichEntity("算盘", "character", tags=["法宝"], description="能打能算")])
    assert graph.entity_tags["算盘"] == ["法宝"]
    assert graph.entity_attributes["算盘"]["description"] == "能打能算"


def test_fact_graph_register_entities_applies_attribute_merge_patch() -> None:
    """2026-08-11 用于验证 entity.attributes JSON Merge Patch：普通值覆盖、null 删除"""
    graph = FactGraph(
        history_entity_types={"算盘": "character"},
        history_entity_names={"算盘": "算盘"},
        history_entity_attributes={"算盘": {"status": "active", "nickname": "老伙计", "description": "能打能算"}},
    )
    graph.register_entities(
        [
            _RichEntity(
                "算盘",
                "character",
                attributes={"status": "retired", "nickname": None},
            )
        ]
    )
    attributes = graph.entity_attributes["算盘"]
    assert attributes["description"] == "能打能算"
    assert attributes["status"] == "retired"
    assert "nickname" not in attributes


def _alias_graph(*, flagged: bool = True) -> FactGraph:
    """2026-08-11 用于构造石轩/小石头同一人物分量图"""
    graph = FactGraph(
        history_entity_types={"石轩": "character", "小石头": "character"},
        history_entity_names={"石轩": "石轩", "小石头": "小石头"},
        history_entity_attributes=({"石轩": {"is_representative": True}, "小石头": {}} if flagged else {}),
    )
    graph.apply_relation(_relation("石轩", "小石头", "同一人物"))
    return graph


def test_resolve_name_uses_representative_flag() -> None:
    """2026-08-11 用于验证沿同一人物分量解析到 is_representative 标记节点"""
    graph = _alias_graph()
    assert graph.resolve_name("小石头") == "石轩"
    assert graph.resolve_name("石轩") == "石轩"


def test_resolve_name_fallback_when_no_flag() -> None:
    """2026-08-11 用于验证无标记时兜底已登记优先"""
    graph = _alias_graph(flagged=False)
    assert graph.resolve_name("小石头") == "石轩"


def test_resolve_name_after_duplicate_relation_submission() -> None:
    """2026-08-12 用于验证已存在同一人物边再次提交为 no-op，别名解析不受影响"""
    graph = _alias_graph()
    assert graph.apply_relation(_relation("石轩", "小石头", "同一人物")) is False
    assert graph.resolve_name("小石头") == "石轩"
