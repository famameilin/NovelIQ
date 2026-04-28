from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_project_env() -> None:
    """在 config 子模块导入前加载 .env，保证环境变量顺序稳定"""

    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)


load_project_env()
