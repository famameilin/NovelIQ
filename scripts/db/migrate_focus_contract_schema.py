"""
创建时间: 2026-04-27
创建者: Codex
任务: protagonist-focus-contract
说明: 将 `cloud_analysis` 从旧单主角合同硬切到新的焦点合同结构。

执行内容:
- 新增 `focus_structure`
- 新增 `focus_characters`
- 删除旧 `protagonist` 列

注意:
- 本脚本按当前任务约定，不兼容旧代码、不兼容旧数据。
- 建议在清空旧分析数据后执行，再启动后端。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


def _apply_focus_contract_upgrade(database_url: str) -> None:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: protagonist-focus-contract
    说明: 对单个数据库执行焦点合同 schema 切换。
    """
    engine = create_engine(database_url)
    print(f"\n=== Upgrading focus contract schema: {database_url} ===")

    statements = [
        "ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS focus_structure VARCHAR(20)",
        "ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS focus_characters TEXT",
        "ALTER TABLE cloud_analysis DROP COLUMN IF EXISTS protagonist",
    ]

    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))

    print("Focus contract schema upgrade completed.")


def main() -> None:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: protagonist-focus-contract
    说明: 从 `.env` 中读取开发库和测试库连接，逐个执行焦点合同切换。
    """
    load_dotenv(project_root / ".env")
    db_urls: list[str] = []
    for env_name in ("DATABASE_URL", "TEST_DATABASE_URL"):
        value = os.getenv(env_name)
        if value:
            db_urls.append(value)

    if not db_urls:
        raise RuntimeError("DATABASE_URL or TEST_DATABASE_URL must be set")

    for database_url in db_urls:
        _apply_focus_contract_upgrade(database_url)


if __name__ == "__main__":
    main()
