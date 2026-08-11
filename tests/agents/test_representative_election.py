"""规范名选举纯函数测试"""

from src.storage.repositories.graph.election import elect_representatives


class FakeEntity:
    def __init__(self, entity_id: int, canonical_name: str) -> None:
        self.entity_id = entity_id
        self.canonical_name = canonical_name
        self.attributes: dict = {}


def test_election_marks_single_component() -> None:
    entities = [FakeEntity(1, "石轩"), FakeEntity(2, "小石头"), FakeEntity(3, "张三")]
    flags = elect_representatives(entities, pairs=[(1, 2)])
    assert flags == {1: True, 2: False, 3: False}


def test_election_chain_converges_to_min_id() -> None:
    entities = [FakeEntity(100, "甲"), FakeEntity(200, "乙"), FakeEntity(300, "丙")]
    flags = elect_representatives(entities, pairs=[(100, 200), (200, 300)])
    assert flags[100] is True
    assert flags[200] is False
    assert flags[300] is False


def test_election_disjoint_components() -> None:
    entities = [FakeEntity(1, "A"), FakeEntity(2, "B"), FakeEntity(3, "C"), FakeEntity(4, "D")]
    flags = elect_representatives(entities, pairs=[(1, 2), (3, 4)])
    assert flags[1] is True and flags[2] is False
    assert flags[3] is True and flags[4] is False
