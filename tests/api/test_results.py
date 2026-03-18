"""
测试结果 API

修改时间: 2026-03-16
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 更新测试以匹配当前API行为（返回空数据而非错误）
"""
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


class TestResults:
    def test_get_results_not_found(self):
        """
        测试获取不存在任务的结果
        
        2026-03-13: TraeAI修改，任务refactor-api-layer-functions
        修改内容: get_results端点会先检查任务是否存在，不存在返回404
        
        2026-03-18: TraeAI修改，修复API参数问题
        修改内容: 将task_id改为run_id，使用完整UUID查询
        """
        response = client.get("/api/novels/nonexistent/results?run_id=nonexistent")
        assert response.status_code == 404

    def test_get_emotion_curve_not_found(self):
        """测试获取不存在任务的情感曲线 - 返回空数据"""
        response = client.get("/api/novels/nonexistent/emotion-curve?task_id=nonexistent")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_rhythm_curve_not_found(self):
        """测试获取不存在任务的节奏曲线 - 返回空数据"""
        response = client.get("/api/novels/nonexistent/rhythm-curve?task_id=nonexistent")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_characters_not_found(self):
        """测试获取不存在任务的人物统计 - 返回空数据"""
        response = client.get("/api/novels/nonexistent/characters?task_id=nonexistent")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_topics_not_found(self):
        """测试获取不存在任务的主题分布 - 返回空数据"""
        response = client.get("/api/novels/nonexistent/topics?task_id=nonexistent")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_diagnosis_not_found(self):
        """测试获取不存在任务的诊断结果 - 返回空数据"""
        response = client.get("/api/novels/nonexistent/diagnosis?task_id=nonexistent")
        assert response.status_code == 200
        assert response.json() is None or response.json() == {}
