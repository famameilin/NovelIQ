"""API 错误处理测试"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.support.storage_fixtures import fixture_id


class TestErrorHandling:
    """测试错误处理"""

    def test_error_response_format(self, api_client: TestClient):
        """测试错误响应格式

        NovelNotFoundError 应返回 404（资源不存在），而非 400
        """
        response = api_client.get(f"/api/novels/{fixture_id(__name__, 'nonexistent')}/results?task_id=nonexist")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "error_type" in data
        assert "status_code" in data

    def test_404_error(self, api_client: TestClient):
        """测试 404 错误"""
        response = api_client.get("/api/nonexistent")
        assert response.status_code == 404

    def test_health_check(self, api_client: TestClient):
        """测试健康检查端点"""
        response = api_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_health_check_returns_generic_message_on_db_failure(self, api_client: TestClient):
        """健康检查失败时 503 body 不得透传内部异常原文，
        错误详情只写日志，对外返回通用文案。
        """
        with patch(
            "src.storage.read_access.ReadAccess.api_main_health_check_1",
            side_effect=RuntimeError("connection refused: postgres://user:secret@internal-host:5432/db"),
        ):
            response = api_client.get("/health")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        assert "secret" not in body["error"]
        assert "internal-host" not in body["error"]
        assert "connection refused" not in body["error"]
        assert body["error"] == "服务暂不可用，请稍后重试"

    def test_http_exception_uses_unified_error_body(self, api_client: TestClient):
        """统一错误 body 契约：路由内 HTTPException（404/409 等）与自定义异常处理器
        统一为三字段格式 {detail, error_type, status_code}。
        """
        response = api_client.get(f"/api/novels/{fixture_id(__name__, 'not-exist-novel-abc')}")
        assert response.status_code == 404
        body = response.json()
        assert set(body.keys()) == {"detail", "error_type", "status_code"}
        assert body["error_type"] == "HTTPException"
        assert body["status_code"] == 404
        assert isinstance(body["detail"], str)

    def test_validation_error_uses_unified_error_body(self, api_client: TestClient):
        """统一错误 body 契约：请求参数校验失败（422）返回三字段格式，
        detail 为可读字符串而非 FastAPI 默认的 [{loc,msg,type}] 列表。
        """
        # timeline 缺 task_id 查询参数 → 确定性 422
        response = api_client.get(f"/api/novels/{fixture_id(__name__, 'not-exist-novel-abc')}/timeline")
        assert response.status_code == 422
        body = response.json()
        assert set(body.keys()) == {"detail", "error_type", "status_code"}
        assert body["error_type"] == "ValidationError"
        assert body["status_code"] == 422
        assert isinstance(body["detail"], str)
