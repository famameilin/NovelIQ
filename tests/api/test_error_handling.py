from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


class TestErrorHandling:
    def test_error_response_format(self):
        """测试错误响应格式

        修改时间: 2026-03-13
        修改者: TraeAI
        任务: refactor-core-data-layer-functions
        修改原因: NovelNotFoundError 应返回 404（资源不存在），而非 400

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: 修复API参数问题
        修改内容: 将task_id改为run_id，使用完整UUID查询

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: API接口参数统一优化
        修改内容: 将run_id参数改回task_id，使用8位短UUID
        """
        response = client.get("/api/novels/nonexistent/results?task_id=nonexist")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "error_type" in data
        assert "status_code" in data

    def test_404_error(self):
        """测试 404 错误"""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404

    def test_health_check(self):
        """测试健康检查端点"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
