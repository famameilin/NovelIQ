"""
API 错误处理测试

修改时间: 2026-04-05
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库
"""

from unittest.mock import patch

from fastapi.testclient import TestClient


class TestErrorHandling:
    """测试错误处理"""

    def test_error_response_format(self, api_client: TestClient):
        """测试错误响应格式

        修改时间: 2026-03-13
        任务: refactor-core-data-layer-functions
        修改原因: NovelNotFoundError 应返回 404（资源不存在），而非 400

        修改时间: 2026-03-18
        任务: 修复API参数问题
        修改内容: 将task_id改为run_id，使用完整UUID查询

        修改时间: 2026-03-19
        任务: API接口参数统一优化
        修改内容: 将run_id参数改回task_id，使用8位短UUID
        """
        response = api_client.get("/api/novels/nonexistent/results?task_id=nonexist")
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
        """
        2026-08-13 P2：健康检查失败时 503 body 不得透传内部异常原文，
        错误详情只写日志，对外返回通用文案。
        """
        with patch(
            "src.storage.db.get_session",
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
        """
        2026-08-13 统一错误 body 契约：路由内 HTTPException（404/409 等）
        此前返回 FastAPI 默认 {detail}，与自定义异常处理器 {detail, error_type, status_code}
        并存两种结构。现在统一为三字段格式。
        """
        response = api_client.get("/api/novels/not-exist-novel-abc")
        assert response.status_code == 404
        body = response.json()
        assert set(body.keys()) == {"detail", "error_type", "status_code"}
        assert body["error_type"] == "HTTPException"
        assert body["status_code"] == 404
        assert isinstance(body["detail"], str)

    def test_validation_error_uses_unified_error_body(self, api_client: TestClient):
        """2026-08-13 统一错误 body 契约：请求参数校验失败（422）返回三字段格式，
        detail 为可读字符串而非 FastAPI 默认的 [{loc,msg,type}] 列表。"""
        # timeline 缺 task_id 查询参数 → 确定性 422
        response = api_client.get("/api/novels/not-exist-novel-abc/timeline")
        assert response.status_code == 422
        body = response.json()
        assert set(body.keys()) == {"detail", "error_type", "status_code"}
        assert body["error_type"] == "ValidationError"
        assert body["status_code"] == 422
        assert isinstance(body["detail"], str)
