import tempfile

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


class TestNovelUpload:
    def test_upload_txt_file(self):
        """测试上传 .txt 文件"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test novel content\n" * 100)
            f.flush()

            with open(f.name, "rb") as file:
                response = client.post(
                    "/api/novels/upload",
                    files={"file": ("test.txt", file, "text/plain")}
                )

        assert response.status_code == 200
        data = response.json()
        assert "novel_id" in data
        assert data["filename"] == "test.txt"
        assert data["status"] == "uploaded"

    def test_upload_invalid_file(self):
        """测试上传无效文件"""
        response = client.post(
            "/api/novels/upload",
            files={"file": ("test.pdf", b"content", "application/pdf")}
        )
        assert response.status_code == 400

    def test_list_novels(self):
        """测试列出小说"""
        response = client.get("/api/novels/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)
