"""用同一隔离数据库与本地模型产物，对照基线与当前源码的完整 API 结果"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def capture_version(source: Path, schema: str, novel_id: str, task_id: str, output: Path) -> None:
    """子进程只替换源码路径，SQL schema、模型文件和数据保持相同"""
    code = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.path.insert(1, sys.argv[2])
from dotenv import load_dotenv
load_dotenv(Path(sys.argv[2]) / '.env')
from sqlalchemy.orm import sessionmaker
from tests.conftest import _build_test_engine, get_test_database_url
from src.storage import db
engine = _build_test_engine(get_test_database_url(), sys.argv[3])
db._engine = engine
db._session_factory = sessionmaker(bind=engine, expire_on_commit=False)
from src.api.main import app
from fastapi.testclient import TestClient
from tests.support.result_contract_snapshot import capture, normalize
# 不进入生产启动生命周期，不做结构升级、恢复或付费模型请求
client = TestClient(app)
try:
    result = normalize(capture(client, sys.argv[4], sys.argv[5]), stable_collections=False)
    Path(sys.argv[6]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
finally:
    client.close()
    engine.dispose()
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(source), str(ROOT), schema, novel_id, task_id, str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    if completed.returncode:
        (output.parent / (output.stem + ".log")).write_text(completed.stdout + completed.stderr, encoding="utf-8")
        raise RuntimeError(f"版本捕获失败，日志: {output.with_suffix('.log')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="0ff05bdea28d2324461c4cfe3bfbd7d3e532f968")
    parser.add_argument("--write-baseline", action="store_true", help="对照通过后保存基线，用于版本化回归")
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "rev-parse", args.baseline], cwd=ROOT, text=True).strip()
    workspace = ROOT / ".pytest-tmp" / ("module_compare_" + uuid.uuid4().hex[:12])
    workspace.mkdir(parents=True)
    archived = subprocess.check_output(["git", "archive", "--format=zip", commit, "src"], cwd=ROOT)
    source = workspace / "baseline"
    with zipfile.ZipFile(io.BytesIO(archived)) as bundle:
        # 内容来自已解析的本仓库提交，仍限制解包路径只能落在本次临时目录
        for member in bundle.namelist():
            if not (source / member).resolve().is_relative_to(source.resolve()):
                raise ValueError(f"非法归档路径: {member}")
        bundle.extractall(source)

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    import pytest
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from src.storage import db
    from tests.conftest import _build_test_engine, _create_all_orm_tables, get_test_database_url
    from tests.support.result_contract_snapshot import ENDPOINTS, normalize, prepare_scenario

    schema = "arch_compare_" + uuid.uuid4().hex[:12]
    assert re.fullmatch(r"arch_compare_[a-f0-9]{12}", schema)
    engine = _build_test_engine(get_test_database_url(), schema)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
            assert conn.execute(text("SELECT current_schema()")).scalar_one() == schema
        _create_all_orm_tables(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        db._engine, db._session_factory = engine, factory
        with pytest.MonkeyPatch.context() as monkeypatch, factory() as session:
            scenario = prepare_scenario(session, monkeypatch)
        old, new = workspace / "baseline.json", workspace / "current.json"
        capture_version(source, schema, scenario.novel_id, scenario.task_id, old)
        capture_version(ROOT, schema, scenario.novel_id, scenario.task_id, new)
        old_data, new_data = json.loads(old.read_text(encoding="utf-8")), json.loads(new.read_text(encoding="utf-8"))
        if old_data != new_data:
            raise AssertionError(f"结果存在差异，完整响应保存在 {workspace}")
        if args.write_baseline:
            target = ROOT / "tests/api/fixtures/module_results_baseline.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    {
                        "baseline_commit": commit,
                        "normalization": ["results.file_path", "export.generated_at"],
                        "unordered_collections": ["graph.edges", "export.character_relations"],
                        "responses": normalize(old_data),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        print(f"完整结果一致: {len(ENDPOINTS)} 个 API 响应及 JSON 导出；证据: {workspace}")
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
        db._engine = db._session_factory = None


if __name__ == "__main__":
    main()
