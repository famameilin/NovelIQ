import json

import pytest

from src.runtime_env import load_database_environment, load_model_environment


def test_load_four_object_environment_fields(monkeypatch) -> None:
    """
    2026-08-03 用于验证数据库与模型对象使用语义化属性
    """

    monkeypatch.setenv(
        "DATABASE",
        json.dumps(
            {
                "url": "postgresql+psycopg://localhost:5432/novel_analysis",
                "username": "postgres",
                "password": "secret",
            }
        ),
    )
    monkeypatch.setenv(
        "MODEL",
        json.dumps(
            {
                "base_url": "https://api.example.com/v1",
                "model": "text-model",
                "api_key": "text-key",
            }
        ),
    )

    database = load_database_environment("DATABASE")
    model = load_model_environment("MODEL")

    assert database is not None
    assert database.username == "postgres"
    assert model.model == "text-model"


@pytest.mark.parametrize(
    ("env_var_name", "raw_value", "message"),
    [
        ("MODEL", "{", "MODEL 必须是有效 JSON 对象"),
        ("MODEL", "[]", "MODEL 必须是 JSON 对象"),
        (
            "MODEL",
            '{"base_url":"https://api.example.com/v1","model":"text-model"}',
            "MODEL.api_key 必须是字符串",
        ),
        (
            "MODEL",
            '{"base_url":"https://api.example.com/v1","model":"","api_key":"key"}',
            "MODEL.model 不能为空",
        ),
    ],
)
def test_load_model_environment_rejects_invalid_contract(
    monkeypatch,
    env_var_name: str,
    raw_value: str,
    message: str,
) -> None:
    """
    2026-08-03 用于验证模型对象错误包含完整字段路径
    """

    monkeypatch.setenv(env_var_name, raw_value)

    with pytest.raises((RuntimeError, ValueError), match=message):
        load_model_environment("MODEL")


def test_load_model_environment_requires_new_variable(monkeypatch) -> None:
    """
    2026-08-03 用于确认旧任务级变量不能替代 MODEL
    """

    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.setenv("ANNOTATION_MODEL", "legacy-model")

    with pytest.raises(RuntimeError, match="MODEL 环境变量未配置"):
        load_model_environment("MODEL")
