"""图结构指标与 TextRank 关键词端点测试"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.api.services.results_queries.graph import compute_graph_metrics
from src.storage.repositories import GraphRepository, RunRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)
from tests.support.paragraph_fixtures import create_run_with_status
from tests.support.run_records import set_run_status
from tests.support.storage_fixtures import fixture_id, storage_for, task_for_run


def _seed_graph(db_session, run_id: str) -> None:
    """三章：林渡-顾霜、林渡-萧遥、顾霜-萧遥 关系 → 人物三角图"""
    for chapter_id, relations in {
        1: [("林渡", "顾霜"), ("林渡", "萧遥")],
        2: [("林渡", "顾霜"), ("顾霜", "萧遥")],
        3: [("林渡", "萧遥"), ("顾霜", "萧遥")],
    }.items():
        persist_chapter_annotation(
            db_session,
            run_id=run_id,
            chapter_id=chapter_id,
            characters=[
                character_fact(chapter_id=chapter_id, name="林渡", action="同行"),
                character_fact(chapter_id=chapter_id, name="顾霜", action="同行"),
                character_fact(chapter_id=chapter_id, name="萧遥", action="同行"),
            ],
            relations=[
                relation_fact(chapter_id=chapter_id, from_name=from_name, to_name=to_name, relation_type="盟友")
                for from_name, to_name in relations
            ],
        )
    db_session.commit()


def _mark_completed(db_session, run_id: str) -> None:
    """create_run_with_chunks 生成的 run 状态回到 completed 以通过读门禁"""
    set_run_status(RunRepository(db_session).session, run_id, "completed")
    from tests.support.chapter_annotation_helpers import confirm_test_work

    confirm_test_work(db_session, run_id)


def test_graph_metrics_returns_pagerank_hits_communities(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌", "萧遥前来助阵", "三人共商大计"],
        chapter_ids=[1, 2, 3],
        title="图指标",
    )
    _seed_graph(db_session, run_id)
    _mark_completed(db_session, run_id)
    assert GraphRepository(db_session).fetch_snapshot(run_id) is not None

    response = api_client.get(
        f"/api/novels/{novel_id}/graph/metrics", params={"task_id": task_for_run(run_id, db_session)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is None
    algorithm = body["algorithm"]
    assert algorithm["name"] == "graph-metrics"
    assert "version" not in algorithm
    assert algorithm["graph"]["node_count"] >= 3
    pagerank = body["pagerank"]
    assert len(pagerank) >= 3
    assert abs(sum(pagerank.values()) - 1.0) < 1e-4
    # 无向图 HITS 对称：authority == hub
    assert set(body["hits"]["authority"].keys()) == set(body["hits"]["hub"].keys())
    assert body["communities"]["interpretation"] == "structural_community_only"
    assert body["communities"]["modularity"] is not None


def test_graph_metrics_accumulates_reverse_relations(monkeypatch) -> None:
    """验证双向端点进入无向图后累加权重而不是相互覆盖"""
    snapshot = {
        "nodes": [
            {"name": "甲", "entity_type": "character"},
            {"name": "乙", "entity_type": "character"},
            {"name": "丙", "entity_type": "character"},
        ],
        "edges": [
            {"source_name": "甲", "target_name": "乙"},
            {"source_name": "乙", "target_name": "甲"},
            {"source_name": "甲", "target_name": "丙"},
        ],
    }
    captured: dict[str, int] = {}

    def capture_pagerank(graph, *, weight: str) -> dict[str, float]:
        """读取 PageRank 收到的规范化无向边权"""
        captured["甲乙"] = int(graph["甲"]["乙"][weight])
        return dict.fromkeys(graph.nodes, 1 / 3)

    monkeypatch.setattr(
        "src.api.services.results_queries.graph._fetch_graph_snapshot",
        MagicMock(return_value=snapshot),
    )
    monkeypatch.setattr("src.metrics.aggregate.algorithms.nx.pagerank", capture_pagerank)

    compute_graph_metrics(fixture_id(__name__, "run-1"), storage_for(MagicMock()))

    assert captured["甲乙"] == 2


def test_graph_metrics_insufficient_nodes(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["孤身一人", "独自前行"],
        chapter_ids=[1, 2],
        title="单人物",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[character_fact(chapter_id=1, name="孤侠", action="独行")],
        relations=[],
    )
    _mark_completed(db_session, run_id)
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{novel_id}/graph/metrics", params={"task_id": task_for_run(run_id, db_session)}
    )
    assert response.status_code == 200
    assert response.json()["unavailable_reason"] is not None


def test_graph_metrics_without_snapshot(api_client: TestClient, db_session) -> None:
    from tests.support.paragraph_fixtures import create_completed_run

    novel_id, run_id = create_completed_run(db_session, chapter_texts=["没有图数据。"])

    response = api_client.get(
        f"/api/novels/{novel_id}/graph/metrics", params={"task_id": task_for_run(run_id, db_session)}
    )
    assert response.status_code == 200
    assert response.json()["unavailable_reason"] is not None


def test_keywords_endpoint_returns_tokens(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[
            "少年握剑，剑光照亮长夜，少年踏上征途。",
            "剑客与少年同行，剑客教导少年。",
            "长夜漫漫，少年握剑而立。",
        ],
        chapter_ids=[1, 2, 3],
        title="关键词",
    )
    _mark_completed(db_session, run_id)

    response = api_client.get(f"/api/novels/{novel_id}/keywords", params={"task_id": task_for_run(run_id, db_session)})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is None
    words = [item["word"] for item in body["keywords"]]
    # 高频实词（少年/剑/长夜/剑客）进入 Top-N
    assert len(body["keywords"]) > 0
    assert body["algorithm"]["window"] == 5
    assert all(len(w) >= 2 for w in words)


def test_keywords_endpoint_empty_paragraphs(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["。"], status="completed")

    response = api_client.get(f"/api/novels/{novel_id}/keywords", params={"task_id": task_for_run(run_id, db_session)})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is not None or body["keywords"] == []


def test_graph_and_keywords_require_completed_run(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["文本。"], status="failed")

    graph_resp = api_client.get(
        f"/api/novels/{novel_id}/graph/metrics", params={"task_id": task_for_run(run_id, db_session)}
    )
    assert graph_resp.status_code == 400
    keyword_resp = api_client.get(
        f"/api/novels/{novel_id}/keywords", params={"task_id": task_for_run(run_id, db_session)}
    )
    assert keyword_resp.status_code == 400


def test_graph_tab_keeps_isolated_characters_without_relation_metrics(api_client: TestClient, db_session) -> None:
    """有效空关系图保留人物与快照，两种读取入口均不能因数值求解失败返回 500"""
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["两人独自行路。", "各自远行。"], chapter_ids=[1, 2], title="孤立人物"
    )
    for chapter_id in (1, 2):
        persist_chapter_annotation(
            db_session,
            run_id=run_id,
            chapter_id=chapter_id,
            characters=[
                character_fact(chapter_id=chapter_id, name="顾承渊", action="独行"),
                character_fact(chapter_id=chapter_id, name="苏映雪", action="远行"),
            ],
            relations=[],
        )
    _mark_completed(db_session, run_id)
    db_session.commit()

    for endpoint in ("graph/metrics", "tabs/graph-network"):
        response = api_client.get(
            f"/api/novels/{novel_id}/{endpoint}", params={"task_id": task_for_run(run_id, db_session)}
        )
        assert response.status_code == 200
        body = response.json()
        if endpoint == "tabs/graph-network":
            assert len(body["snapshot"]["nodes"]) == 2
            assert body["snapshot"]["edges"] == []
            body = body["graph_metrics"]
        assert body["algorithm"]["graph"]["edge_count"] == 0
        assert body["pagerank"] == {"顾承渊": 0.5, "苏映雪": 0.5}
        assert body["hits"]["authority"] == body["hits"]["hub"] == {}
        assert body["hits"]["unavailable_reason"].startswith("no_relations:")
        assert body["communities"]["modularity"] is None
        assert body["communities"]["unavailable_reason"].startswith("no_relations:")
