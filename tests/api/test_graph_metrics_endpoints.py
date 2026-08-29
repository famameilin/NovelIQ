"""图结构指标与 TextRank 关键词端点测试（赛道 A1/A2/A3）"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.storage.repositories import GraphRepository, RunRepository
from tests.support.chapter_annotation_helpers import (
    character_fact,
    create_run_with_chunks,
    persist_chapter_annotation,
    relation_fact,
)
from tests.support.paragraph_fixtures import create_run_with_status


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
                character_fact(chunk_id=chapter_id, name="林渡", action="同行"),
                character_fact(chunk_id=chapter_id, name="顾霜", action="同行"),
                character_fact(chunk_id=chapter_id, name="萧遥", action="同行"),
            ],
            relations=[
                relation_fact(chunk_id=chapter_id, from_name=from_name, to_name=to_name, relation_type="盟友")
                for from_name, to_name in relations
            ],
        )
    db_session.commit()




def _mark_completed(db_session, run_id: str) -> None:
    """create_run_with_chunks 生成的 run 状态回到 completed 以通过读门禁"""
    RunRepository(db_session).update_run_status(run_id, "completed")

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

    response = api_client.get(f"/api/novels/{novel_id}/graph/metrics", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is None
    algorithm = body["algorithm"]
    assert algorithm["version"].startswith("graph-metrics")
    assert algorithm["graph"]["node_count"] >= 3
    pagerank = body["pagerank"]
    assert len(pagerank) >= 3
    assert abs(sum(pagerank.values()) - 1.0) < 1e-4
    # 无向图 HITS 对称：authority == hub
    assert set(body["hits"]["authority"].keys()) == set(body["hits"]["hub"].keys())
    assert body["communities"]["interpretation"] == "structural_community_only"
    assert body["communities"]["modularity"] is not None


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
        characters=[character_fact(chunk_id=1, name="孤侠", action="独行")],
        relations=[],
    )
    _mark_completed(db_session, run_id)
    db_session.commit()

    response = api_client.get(f"/api/novels/{novel_id}/graph/metrics", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    assert response.json()["unavailable_reason"] is not None


def test_graph_metrics_without_snapshot(api_client: TestClient, db_session) -> None:
    from tests.support.paragraph_fixtures import create_completed_run

    novel_id, run_id = create_completed_run(db_session, chapter_texts=["没有图数据。"])

    response = api_client.get(f"/api/novels/{novel_id}/graph/metrics", params={"task_id": run_id[:8]})
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

    response = api_client.get(f"/api/novels/{novel_id}/keywords", params={"task_id": run_id[:8]})
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

    response = api_client.get(f"/api/novels/{novel_id}/keywords", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable_reason"] is not None or body["keywords"] == []


def test_graph_and_keywords_require_completed_run(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_run_with_status(db_session, chapter_texts=["文本。"], status="failed")

    graph_resp = api_client.get(f"/api/novels/{novel_id}/graph/metrics", params={"task_id": run_id[:8]})
    assert graph_resp.status_code == 400
    keyword_resp = api_client.get(f"/api/novels/{novel_id}/keywords", params={"task_id": run_id[:8]})
    assert keyword_resp.status_code == 400