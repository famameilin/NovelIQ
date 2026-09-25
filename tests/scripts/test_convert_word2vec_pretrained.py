"""convert_word2vec_pretrained.py 一次性转换脚本测试"""

from __future__ import annotations

from pathlib import Path

import pytest
from gensim.models import KeyedVectors

from scripts.tools.convert_word2vec_pretrained import (
    convert_pretrained_to_kv,
    read_vector_size,
    resolve_pretrained_file,
)

_WORDS = ["江湖", "刀光", "恩仇", "侠"]
_DIM = 4


def _write_source(directory: Path, name: str = "fixture.vec") -> Path:
    """2026-08-30 用于在临时目录生成最小预训练词向量源文件"""
    path = directory / name
    lines = [f"{len(_WORDS)} {_DIM}"]
    for i, word in enumerate(_WORDS):
        vec = " ".join(f"{(i + j) / 10:.1f}" for j in range(_DIM))
        lines.append(f"{word} {vec}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_resolve_pretrained_file_picks_text_format(tmp_path: Path) -> None:
    """2026-08-30 用于验证转换工具识别文本格式预训练源文件"""
    source = _write_source(tmp_path)
    path, binary = resolve_pretrained_file(tmp_path)
    assert path == source
    assert binary is False


def test_resolve_pretrained_file_missing_dir_raises(tmp_path: Path) -> None:
    """2026-08-30 用于验证预训练源目录缺失时明确报错"""
    with pytest.raises(FileNotFoundError):
        resolve_pretrained_file(tmp_path / "nope")


def test_read_vector_size_reads_header_only(tmp_path: Path) -> None:
    """2026-08-30 用于验证向量维度仅从源文件头读取"""
    source = _write_source(tmp_path)
    assert read_vector_size(source) == _DIM


def test_convert_pretrained_to_kv_roundtrip(tmp_path: Path) -> None:
    """2026-08-30 用于验证文本向量转换为 kv 后可完整加载"""
    source = _write_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    kv_path = convert_pretrained_to_kv(source, binary=False, output_dir=output)
    assert kv_path == output / "fixture.kv"
    assert kv_path.exists()

    loaded = KeyedVectors.load(str(kv_path))
    assert loaded.vector_size == _DIM
    assert all(word in loaded for word in _WORDS)
    # 文本源第 i 个词第 j 维 = (i + j) / 10
    assert loaded[_WORDS[0]][0] == pytest.approx(0.0, abs=1e-6)
    assert loaded[_WORDS[1]][2] == pytest.approx(0.3, abs=1e-6)


def test_convert_pretrained_to_kv_missing_output_raises(tmp_path: Path) -> None:
    """2026-08-30 用于验证输出目录缺失时拒绝转换"""
    source = _write_source(tmp_path)
    with pytest.raises(FileNotFoundError):
        convert_pretrained_to_kv(source, binary=False, output_dir=tmp_path / "nope")


def test_convert_pretrained_to_kv_rejects_second_kv_file(tmp_path: Path) -> None:
    """2026-08-30 用于验证转换脚本不会在共享目录产生第二个 kv 主文件"""
    source = _write_source(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    (output / "existing.kv").touch()

    with pytest.raises(ValueError):
        convert_pretrained_to_kv(source, binary=False, output_dir=output)
