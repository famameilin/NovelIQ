"""一次性转换预训练中文词向量为 gensim KeyedVectors 二进制

预训练源文件默认从 models/word2vec/pretrained 读取，转换产物默认写入
models/word2vec/shared。运行时只加载该目录唯一的 .kv 主文件，并通过
同名数组旁路文件实现只读内存映射，避免重复解析大型文本向量文件

用法：
    python -m scripts.tools.convert_word2vec_pretrained
    python -m scripts.tools.convert_word2vec_pretrained --source <dir> --output <dir>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gensim.models import KeyedVectors

from src.storage.path_resolver import resolve_project_root

#: 预训练词向量源文件目录（相对项目根）
_DEFAULT_SOURCE_DIR = Path("models/word2vec/pretrained")
#: 预训练共享模型产物目录（相对项目根）
_DEFAULT_OUTPUT_DIR = Path("models/word2vec/shared")

#: 预训练词向量文件后缀到 word2vec 二进制格式标志的映射
_PRETRAINED_SUFFIXES = {".bin": True, ".vec": False, ".txt": False}


def resolve_pretrained_file(model_dir: Path) -> tuple[Path, bool]:
    """2026-08-30 用于定位目录内首个受支持的预训练词向量源文件"""
    if not model_dir.is_dir():
        raise FileNotFoundError(f"预训练词向量目录不存在: {model_dir}")
    candidates = sorted(
        path for path in model_dir.glob("*") if path.is_file() and path.suffix.lower() in _PRETRAINED_SUFFIXES
    )
    if not candidates:
        raise FileNotFoundError(f"预训练词向量目录中无可加载的词向量文件: {model_dir}")
    path = candidates[0]
    return path, _PRETRAINED_SUFFIXES[path.suffix.lower()]


def read_vector_size(path: Path) -> int:
    """2026-08-30 用于从 word2vec 文件头读取向量维度而不解析完整文件"""
    with path.open("rb") as fin:
        header = fin.readline()
    parts = header.split()
    if len(parts) < 2 or not parts[-1].isdigit():
        raise ValueError(f"预训练词向量文件头无法解析维度: {path}（首行 {header[:64]!r}）")
    return int(parts[-1])


def convert_pretrained_to_kv(source: Path, *, binary: bool, output_dir: Path) -> Path:
    """2026-08-30 用于转换预训练向量并维持共享目录唯一 kv 主文件契约"""
    if not output_dir.is_dir():
        raise FileNotFoundError(f"预训练模型输出目录不存在: {output_dir}")
    kv_path = output_dir / f"{source.stem}.kv"
    other_kv_files = sorted(
        path for path in output_dir.glob("*.kv") if path.is_file() and path.resolve() != kv_path.resolve()
    )
    if other_kv_files:
        names = ", ".join(path.name for path in other_kv_files)
        raise ValueError(f"预训练共享模型目录必须恰好包含一个 .kv 文件，请先处理已有文件: {names}")
    vectors = KeyedVectors.load_word2vec_format(str(source), binary=binary)
    vectors.save(str(kv_path))
    return kv_path


def main() -> int:
    """2026-08-30 用于解析命令行参数并执行预训练词向量转换"""
    parser = argparse.ArgumentParser(description="转换预训练词向量为 .kv 二进制")
    parser.add_argument("--source", type=Path, default=_DEFAULT_SOURCE_DIR, help="预训练源文件目录")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT_DIR, help="产物 .kv 输出目录")
    args = parser.parse_args()

    root = resolve_project_root()
    source_dir = args.source if args.source.is_absolute() else root / args.source
    output_dir = args.output if args.output.is_absolute() else root / args.output

    try:
        source, binary = resolve_pretrained_file(source_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        kv_path = convert_pretrained_to_kv(source, binary=binary, output_dir=output_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(f"转换预训练词向量: {source} (binary={binary})")
    print(f"完成: {kv_path}（维度 {read_vector_size(source)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
