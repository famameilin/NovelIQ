"""
ArtifactGcService 单元测试。

创建时间: 2026-04-23
任务: p2-artifact-gc-service
说明: 覆盖 task 输出、日志目录与小说源文件清理行为，保护新拆出的文件系统边界。
"""

from __future__ import annotations

from pathlib import Path

from src.api.services.artifact_gc_service import ArtifactGcService


def test_delete_task_artifacts_removes_output_and_both_log_dir_variants(tmp_path: Path) -> None:
    """应清理 output 文件与 full/short 两种日志目录兼容路径。"""
    logs_dir = tmp_path / "logs"
    outputs_dir = tmp_path / "outputs"
    logs_dir.mkdir()
    outputs_dir.mkdir()

    task_id = "abcd1234"
    run_id = "abcd1234-full-run-id"

    (outputs_dir / f"{task_id}.json").write_text("{}", encoding="utf-8")
    (logs_dir / run_id).mkdir()
    (logs_dir / task_id).mkdir()

    service = ArtifactGcService(logs_dir=logs_dir, outputs_dir=outputs_dir)
    service.delete_task_artifacts(task_id, run_id)

    assert not (outputs_dir / f"{task_id}.json").exists()
    assert not (logs_dir / run_id).exists()
    assert not (logs_dir / task_id).exists()


def test_delete_novel_source_file_only_removes_existing_file(tmp_path: Path) -> None:
    """应只删除真实存在的源文件，空路径和缺失文件不报错。"""
    source_file = tmp_path / "novel.txt"
    source_file.write_text("hello", encoding="utf-8")

    service = ArtifactGcService(logs_dir=tmp_path / "logs", outputs_dir=tmp_path / "outputs")
    service.delete_novel_source_file(str(source_file))
    service.delete_novel_source_file(str(source_file))
    service.delete_novel_source_file(None)

    assert not source_file.exists()
