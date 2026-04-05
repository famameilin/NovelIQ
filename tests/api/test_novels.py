"""
API 小说端点测试

修改时间: 2026-04-05
修改者: AI Assistant
任务: fix-test-data-pollution
修改内容: 使用 api_client fixture 确保测试使用测试数据库
"""
import tempfile

from fastapi.testclient import TestClient


class TestNovelUpload:
    """测试小说上传"""

    def test_upload_txt_file(self, api_client: TestClient):
        """测试上传 .txt 文件"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                response = api_client.post(
                    "/api/novels/upload",
                    files={"file": ("test.txt", file, "text/plain")}
                )

        assert response.status_code == 200
        data = response.json()
        assert "novel_id" in data
        assert data["filename"] == "test.txt"
        assert data["status"] == "uploaded"

    def test_upload_invalid_file(self, api_client: TestClient):
        """测试上传无效文件"""
        response = api_client.post(
            "/api/novels/upload",
            files={"file": ("test.pdf", b"content", "application/pdf")}
        )
        assert response.status_code == 400

    def test_list_novels(self, api_client: TestClient):
        """测试列出小说"""
        response = api_client.get("/api/novels/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)
