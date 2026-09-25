"""
ArtifactGcService 单元测试。

创建时间: 2026-04-23
任务: p2-artifact-gc-service
说明: 覆盖 task 输出、日志目录与小说源文件清理行为，保护新拆出的文件系统边界。
"""

from __future__ import annotations

from pathlib import Path

from src.api.services.artifact_gc_service import ArtifactGcService


def test_delete_task_artifacts_removes_output_logs_and_run_model(monkeypatch, tmp_path: Path) -> None:
    """2026-08-30 用于验证任务清理包含 run 模型且保留共享预训练产物"""
    logs_dir = tmp_path / "logs"
    outputs_dir = tmp_path / "outputs"
    logs_dir.mkdir()
    outputs_dir.mkdir()

    task_id = "abcd1234"
    run_id = "abcd1234-full-run-id"

    (outputs_dir / f"{task_id}.json").write_text("{}", encoding="utf-8")
    (logs_dir / run_id).mkdir()
    (logs_dir / task_id).mkdir()
    run_model_dir = tmp_path / "models" / "word2vec" / run_id
    run_model_dir.mkdir(parents=True)
    (run_model_dir / "word2vec.model").write_text("model", encoding="utf-8")
    shared_dir = tmp_path / "models" / "word2vec" / "shared"
    shared_dir.mkdir()
    (shared_dir / "fixture.kv").write_text("shared", encoding="utf-8")

    def resolve_test_run_model_dir(candidate_run_id: str, kind: str) -> Path:
        """2026-08-30 用于把 GC 路径解析隔离到临时测试目录"""
        assert candidate_run_id == run_id
        assert kind == "word2vec"
        return run_model_dir

    monkeypatch.setattr(
        "src.api.services.artifact_gc_service.resolve_run_model_dir",
        resolve_test_run_model_dir,
    )

    service = ArtifactGcService(logs_dir=logs_dir, outputs_dir=outputs_dir)
    service.delete_task_artifacts(task_id, run_id)

    assert not (outputs_dir / f"{task_id}.json").exists()
    assert not (logs_dir / run_id).exists()
    assert not (logs_dir / task_id).exists()
    assert not run_model_dir.exists()
    assert (shared_dir / "fixture.kv").exists()


def test_delete_novel_source_file_only_removes_existing_file(tmp_path: Path) -> None:
    """应只删除真实存在的源文件，空路径和缺失文件不报错。"""
    source_file = tmp_path / "novel.txt"
    source_file.write_text("hello", encoding="utf-8")

    service = ArtifactGcService(logs_dir=tmp_path / "logs", outputs_dir=tmp_path / "outputs")
    service.delete_novel_source_file(str(source_file))
    service.delete_novel_source_file(str(source_file))
    service.delete_novel_source_file(None)

    assert not source_file.exists()
