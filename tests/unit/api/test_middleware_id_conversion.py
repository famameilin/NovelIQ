"""
创建时间: 2026-03-19
创建者: TraeAI
任务: ID系统统一优化 - API中间件ID转换单元测试
说明: 测试API层的ID转换工具函数

修改记录:
- 2026-03-19 TraeAI 初始创建
"""

import pytest
from unittest.mock import Mock, AsyncMock

from fastapi import Request
from fastapi.responses import JSONResponse

from src.api.middleware import (
    convert_task_id_to_run_id,
    convert_run_id_to_task_id,
    convert_response_data,
    task_id_not_found_handler,
    id_mapping_error_handler,
)
from src.storage.id_mapping import TaskIDNotFoundError, IDMappingError


class TestConvertTaskIDToRunID:
    """测试convert_task_id_to_run_id函数"""

    def test_converts_valid_task_id(self):
        """测试转换有效的task_id"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = "3a25baca-1a72-4444-a772-2ddc64334cd2"
        mock_conn.execute.return_value = mock_result

        run_id = convert_task_id_to_run_id("3a25baca", mock_conn)
        assert run_id == "3a25baca-1a72-4444-a772-2ddc64334cd2"

    def test_raises_error_for_invalid_task_id(self):
        """测试无效task_id抛出异常"""
        mock_conn = Mock()

        with pytest.raises(ValueError, match="Invalid task_id"):
            convert_task_id_to_run_id("invalid", mock_conn)


class TestConvertRunIDToTaskID:
    """测试convert_run_id_to_task_id函数"""

    def test_converts_valid_run_id(self):
        """测试转换有效的run_id"""
        run_id = "0211f894-1a72-4444-a772-2ddc64334cd2"
        task_id = convert_run_id_to_task_id(run_id)
        assert task_id == "0211f894"

    def test_raises_error_for_invalid_run_id(self):
        """测试无效run_id抛出异常"""
        with pytest.raises(ValueError, match="Invalid run_id"):
            convert_run_id_to_task_id("")


class TestConvertResponseData:
    """测试convert_response_data函数"""

    def test_converts_run_id_in_dict(self):
        """测试转换字典中的run_id"""
        data = {"run_id": "0211f894-1a72-4444-a772-2ddc64334cd2", "name": "test"}
        result = convert_response_data(data)
        assert result == {"task_id": "0211f894", "name": "test"}

    def test_converts_run_id_in_nested_structure(self):
        """测试转换嵌套结构中的run_id"""
        data = {
            "items": [
                {"run_id": "0211f894-1a72-4444-a772-2ddc64334cd2", "name": "item1"},
                {"run_id": "3a25baca-1a72-4444-a772-2ddc64334cd2", "name": "item2"}
            ]
        }
        result = convert_response_data(data)
        assert result["items"][0]["task_id"] == "0211f894"
        assert result["items"][1]["task_id"] == "3a25baca"


class TestTaskIDNotFoundHandler:
    """测试task_id_not_found_handler函数"""

    @pytest.mark.asyncio
    async def test_returns_404_response(self):
        """测试返回404响应"""
        mock_request = Mock(spec=Request)
        exc = TaskIDNotFoundError("Task not found: abc12345")

        response = await task_id_not_found_handler(mock_request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 404
        content = response.body.decode()
        assert "Task not found" in content
        assert "TaskIDNotFoundError" in content


class TestIDMappingErrorHandler:
    """测试id_mapping_error_handler函数"""

    @pytest.mark.asyncio
    async def test_returns_400_response(self):
        """测试返回400响应"""
        mock_request = Mock(spec=Request)
        exc = IDMappingError("Invalid ID mapping")

        response = await id_mapping_error_handler(mock_request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        content = response.body.decode()
        assert "Invalid ID mapping" in content
        assert "IDMappingError" in content
