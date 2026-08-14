"""
创建时间: 2026-03-19
任务: ID系统统一优化 - API中间件ID转换单元测试
说明: 测试API层的异常处理器

修改记录:
- 2026-03-19 初始创建
- 2026-08-13 移除已删除的 ID 转换工具函数测试（转换逻辑收敛到 src/storage/id_mapping）
"""

from unittest.mock import Mock

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from src.api.middleware import (
    id_mapping_error_handler,
    task_id_not_found_handler,
)
from src.storage.id_mapping import IDMappingError, TaskIDNotFoundError


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
