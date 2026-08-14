"""
API 图谱端点测试

修改时间: 2026-04-05
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库
"""

from fastapi.testclient import TestClient


def test_get_graph_not_found_returns_empty_object(api_client: TestClient):
    response = api_client.get("/api/novels/nonexistent/graph?task_id=nonexistent")
    assert response.status_code == 404


def test_graph_change_limit_has_single_source() -> None:
    """
    2026-08-13 P2：GRAPH_CHANGE_LIMIT 必须单一来源，
    路由（Query le 上限与默认值）与查询组装器引用同一常量对象。
    """
    from src.api.routes import results as results_mod
    from src.api.services.results_queries.graph import GRAPH_CHANGE_LIMIT

    assert results_mod.GRAPH_CHANGE_LIMIT is GRAPH_CHANGE_LIMIT
    assert GRAPH_CHANGE_LIMIT == 200
