"""
创建时间: 2026-03-19
创建者: TraeAI
任务: ID系统统一优化 - id_mapping模块单元测试
说明: 测试ID映射工具模块的各项功能

修改记录:
- 2026-03-19 TraeAI 初始创建
"""

from unittest.mock import Mock

import pytest

from src.storage.id_mapping import (
    IDMappingError,
    TaskIDNotFoundError,
    convert_response_run_ids_to_task_ids,
    generate_run_id,
    generate_task_id,
    run_id_to_task_id,
    task_id_to_run_id,
    task_id_to_run_id_pattern,
)


class TestGenerateRunID:
    """测试generate_run_id函数"""

    def test_returns_36_character_uuid(self):
        """测试返回36位UUID"""
        run_id = generate_run_id()
        assert len(run_id) == 36
        assert "-" in run_id

    def test_returns_unique_values(self):
        """测试每次生成不同的UUID"""
        run_id1 = generate_run_id()
        run_id2 = generate_run_id()
        assert run_id1 != run_id2

    def test_valid_uuid_format(self):
        """测试UUID格式正确"""
        run_id = generate_run_id()
        parts = run_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12


class TestGenerateTaskID:
    """测试generate_task_id函数"""

    def test_returns_8_character_string(self):
        """测试返回8位字符串"""
        task_id = generate_task_id()
        assert len(task_id) == 8

    def test_returns_unique_values(self):
        """测试每次生成不同的task_id"""
        task_id1 = generate_task_id()
        task_id2 = generate_task_id()
        assert task_id1 != task_id2

    def test_contains_only_hex_characters(self):
        """测试只包含十六进制字符"""
        task_id = generate_task_id()
        assert all(c in "0123456789abcdef" for c in task_id)


class TestRunIDToTaskID:
    """测试run_id_to_task_id函数"""

    def test_extracts_first_8_characters(self):
        """测试正确提取前8位"""
        run_id = "0211f894-1a72-4444-a772-2ddc64334cd2"
        task_id = run_id_to_task_id(run_id)
        assert task_id == "0211f894"

    def test_raises_error_for_empty_string(self):
        """测试空字符串抛出异常"""
        with pytest.raises(ValueError, match="Invalid run_id"):
            run_id_to_task_id("")

    def test_raises_error_for_none(self):
        """测试None抛出异常"""
        with pytest.raises(ValueError, match="Invalid run_id"):
            run_id_to_task_id(None)

    def test_raises_error_for_short_string(self):
        """测试短字符串抛出异常"""
        with pytest.raises(ValueError, match="Invalid run_id"):
            run_id_to_task_id("1234567")

    def test_handles_exactly_8_characters(self):
        """测试正好8位字符"""
        run_id = "0211f894"
        task_id = run_id_to_task_id(run_id)
        assert task_id == "0211f894"


class TestTaskIDToRunIDPattern:
    """测试task_id_to_run_id_pattern函数"""

    def test_returns_like_pattern(self):
        """测试返回正确的LIKE模式"""
        task_id = "3a25baca"
        pattern = task_id_to_run_id_pattern(task_id)
        assert pattern == "3a25baca%"

    def test_raises_error_for_empty_string(self):
        """测试空字符串抛出异常"""
        with pytest.raises(ValueError, match="Invalid task_id"):
            task_id_to_run_id_pattern("")

    def test_raises_error_for_none(self):
        """测试None抛出异常"""
        with pytest.raises(ValueError, match="Invalid task_id"):
            task_id_to_run_id_pattern(None)

    def test_raises_error_for_short_string(self):
        """测试短字符串抛出异常"""
        with pytest.raises(ValueError, match="Invalid task_id"):
            task_id_to_run_id_pattern("1234567")

    def test_raises_error_for_long_string(self):
        """测试长字符串抛出异常"""
        with pytest.raises(ValueError, match="Invalid task_id"):
            task_id_to_run_id_pattern("123456789")


class TestTaskIDToRunID:
    """测试task_id_to_run_id函数"""

    def test_returns_run_id_from_database(self):
        """测试从数据库获取run_id"""
        # 模拟数据库连接和查询结果
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = "3a25baca-1a72-4444-a772-2ddc64334cd2"
        mock_conn.execute.return_value = mock_result

        run_id = task_id_to_run_id("3a25baca", mock_conn)
        assert run_id == "3a25baca-1a72-4444-a772-2ddc64334cd2"

    def test_raises_error_when_not_found(self):
        """测试找不到时抛出异常"""
        mock_conn = Mock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_conn.execute.return_value = mock_result

        with pytest.raises(TaskIDNotFoundError, match="No run_id found for task_id"):
            task_id_to_run_id("3a25baca", mock_conn)

    def test_raises_error_for_invalid_task_id(self):
        """测试无效task_id抛出异常"""
        mock_conn = Mock()

        with pytest.raises(ValueError, match="Invalid task_id"):
            task_id_to_run_id("invalid", mock_conn)


class TestConvertResponseRunIDsToTaskIDs:
    """测试convert_response_run_ids_to_task_ids函数"""

    def test_converts_run_id_to_task_id_in_dict(self):
        """测试将字典中的run_id转换为task_id"""
        data = {"run_id": "0211f894-1a72-4444-a772-2ddc64334cd2", "name": "test"}
        result = convert_response_run_ids_to_task_ids(data)
        assert result == {"task_id": "0211f894", "name": "test"}

    def test_converts_run_id_in_nested_dict(self):
        """测试转换嵌套字典中的run_id"""
        data = {
            "name": "parent",
            "child": {"run_id": "0211f894-1a72-4444-a772-2ddc64334cd2", "value": 123}
        }
        result = convert_response_run_ids_to_task_ids(data)
        assert result["child"]["task_id"] == "0211f894"
        assert "run_id" not in result["child"]

    def test_converts_run_id_in_list(self):
        """测试转换列表中的run_id"""
        data = [
            {"run_id": "0211f894-1a72-4444-a772-2ddc64334cd2", "name": "item1"},
            {"run_id": "3a25baca-1a72-4444-a772-2ddc64334cd2", "name": "item2"}
        ]
        result = convert_response_run_ids_to_task_ids(data)
        assert result[0]["task_id"] == "0211f894"
        assert result[1]["task_id"] == "3a25baca"

    def test_preserves_other_fields(self):
        """测试保留其他字段不变"""
        data = {
            "run_id": "0211f894-1a72-4444-a772-2ddc64334cd2",
            "name": "test",
            "count": 42,
            "nested": {"key": "value"}
        }
        result = convert_response_run_ids_to_task_ids(data)
        assert result["name"] == "test"
        assert result["count"] == 42
        assert result["nested"] == {"key": "value"}

    def test_handles_non_36_char_run_id(self):
        """测试不转换非36位的run_id值"""
        data = {"run_id": "short-id", "name": "test"}
        result = convert_response_run_ids_to_task_ids(data)
        # 非36位的run_id值不会被转换
        assert result["run_id"] == "short-id"

    def test_handles_empty_dict(self):
        """测试处理空字典"""
        data = {}
        result = convert_response_run_ids_to_task_ids(data)
        assert result == {}

    def test_handles_empty_list(self):
        """测试处理空列表"""
        data = []
        result = convert_response_run_ids_to_task_ids(data)
        assert result == []


class TestIDMappingError:
    """测试ID映射异常类"""

    def test_id_mapping_error_is_exception(self):
        """测试IDMappingError是Exception的子类"""
        assert issubclass(IDMappingError, Exception)

    def test_task_id_not_found_error_is_id_mapping_error(self):
        """测试TaskIDNotFoundError是IDMappingError的子类"""
        assert issubclass(TaskIDNotFoundError, IDMappingError)

    def test_can_raise_and_catch_task_id_not_found_error(self):
        """测试可以抛出和捕获TaskIDNotFoundError"""
        with pytest.raises(TaskIDNotFoundError):
            raise TaskIDNotFoundError("Test error")

        with pytest.raises(IDMappingError):
            raise TaskIDNotFoundError("Test error")
