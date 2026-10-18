"""经应用注册表取出 ID 转换异常处理器，断言 HTTP 契约（状态码 + 三字段 body）

- 改为按异常类型从注册表取处理器，不再绑定处理器函数名
"""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.middleware import register_exception_handlers
from src.storage.id_mapping import IDMappingError, TaskIDNotFoundError


@pytest.fixture
def registered_handlers() -> dict:
    app = FastAPI()
    register_exception_handlers(app)
    return app.exception_handlers


class TestTaskIDNotFoundHandler:
    """TaskIDNotFoundError → 404「任务不存在」契约"""

    @pytest.mark.asyncio
    async def test_returns_404_response(self, registered_handlers: dict):
        """测试返回404响应"""
        mock_request = Mock(spec=Request)
        exc = TaskIDNotFoundError("Task not found: abc12345")

        response = await registered_handlers[TaskIDNotFoundError](mock_request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 404
        content = response.body.decode()
        assert "Task not found" in content
        assert "TaskIDNotFoundError" in content


class TestIDMappingErrorHandler:
    """IDMappingError → 400 契约"""

    @pytest.mark.asyncio
    async def test_returns_400_response(self, registered_handlers: dict):
        """测试返回400响应"""
        mock_request = Mock(spec=Request)
        exc = IDMappingError("Invalid ID mapping")

        response = await registered_handlers[IDMappingError](mock_request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        content = response.body.decode()
        assert "Invalid ID mapping" in content
        assert "IDMappingError" in content
