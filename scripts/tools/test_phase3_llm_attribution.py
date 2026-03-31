"""
Phase3 对话归属测试 — 使用正式 AnnotationClient 入口测试 LLM

创建时间: 2026-03-31
创建者: TraeAI
任务: fix-phase3-speaker-identity-clue-mismatch
说明: 使用正式 API 入口测试修复后的对话归属功能，对比旧结果

测试数据: 从数据库读取真实 chunk

输出: 实时打印到控制台，同时写入日志文件
"""

import sys
import os
import time
import io
from datetime import datetime

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, _project_root)

# 设置无缓冲输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

from dotenv import load_dotenv
load_dotenv(os.path.join(_project_root, '.env'))

import src.config
from src.models.annotation import AnnotationClient


class TeeLogger:
    """双日志输出：同时写入文件和控制台"""
    def __init__(self, file_path: str):
        self.file = open(file_path, 'w', encoding='utf-8')
        self.console = sys.stdout
        self.file_path = file_path

    def write(self, message: str):
        self.file.write(message)
        self.console.write(message)
        self.flush()

    def flush(self):
        self.file.flush()
        self.console.flush()

    def close(self):
        self.file.close()

    def __enter__(self):
        sys.stdout = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.console
        self.close()
        return False
from src.models.local.annotation.phase3 import (
    extract_dialogues_from_text,
    compute_dialogue_lengths_with_llm,
)
from src.models.local.schema import DialogueRecord
from src.storage.db import get_session
from src.storage.repositories.chunk_repository import ChunkRepository
from sqlalchemy import text as sa_text


def get_old_results_from_db(session, chunk_id: int, run_id: str) -> list[dict]:
    """从数据库获取旧结果"""
    result = session.execute(
        sa_text("""
            SELECT chunk_id, speaker, length, tone, content, identity_clue
            FROM chunk_dialogues
            WHERE chunk_id = :chunk_id AND run_id = :run_id
            ORDER BY id
        """),
        {"chunk_id": chunk_id, "run_id": run_id}
    )
    return [
        {
            "chunk_id": row[0],
            "speaker": row[1],
            "length": row[2],
            "tone": row[3],
            "content": row[4],
            "identity_clue": row[5],
        }
        for row in result.fetchall()
    ]


def get_known_characters_from_db(session, run_id: str) -> list[str]:
    """从数据库获取已知角色列表"""
    result = session.execute(
        sa_text("""
            SELECT DISTINCT name FROM chunk_characters
            WHERE run_id = :run_id
            ORDER BY name
        """),
        {"run_id": run_id}
    )
    return [row[0] for row in result.fetchall()]


def format_comparison(
    old_results: list[dict],
    new_records: list[DialogueRecord],
    candidates: list,
) -> dict:
    """格式化对比结果"""
    old_by_index = {i+1: r for i, r in enumerate(old_results)}
    new_by_index = {r.index: r for r in new_records}

    comparison = []
    max_len = max(len(old_by_index), len(new_by_index))

    for idx in range(1, max_len + 1):
        old = old_by_index.get(idx, {})
        new = new_by_index.get(idx)
        content = old.get("content") or (new.content if new else "")

        old_speaker = old.get("speaker")
        new_speaker = new.speaker if new else None

        is_same = old_speaker == new_speaker
        is_improved = old_speaker is None and new_speaker is not None
        is_regression = old_speaker is not None and new_speaker is None

        comparison.append({
            "index": idx,
            "content": content[:30] + "..." if len(content) > 30 else content,
            "old_speaker": old_speaker,
            "new_speaker": new_speaker,
            "identity_clue": new.identity_clue if new else None,
            "is_same": is_same,
            "is_improved": is_improved,
            "is_regression": is_regression,
        })

    return comparison


def print_comparison_table(comparison: list[dict], chunk_id: int) -> None:
    """打印对比表格"""
    print(f"\n{'='*80}")
    print(f"Chunk {chunk_id} 对话归属对比结果")
    print(f"{'='*80}")
    print(f"{'Idx':<4} {'内容':<25} {'旧speaker':<12} {'新speaker':<12} {'状态':<10}")
    print(f"{'-'*80}")

    improved_count = 0
    regression_count = 0
    same_count = 0

    for item in comparison:
        if item["is_improved"]:
            improved_count += 1
            status = "[OK] improved"
        elif item["is_regression"]:
            regression_count += 1
            status = "[X] regression"
        else:
            same_count += 1
            status = "[=] same"

        old_sp = item["old_speaker"] or "(null)"
        new_sp = item["new_speaker"] or "(null)"

        print(f"{item['index']:<4} {item['content']:<25} {old_sp:<12} {new_sp:<12} {status}")

        if item["identity_clue"]:
            print(f"     └── clue: {item['identity_clue'][:50]}...")

    print(f"{'-'*80}")
    print(f"统计: 相同={same_count}, 改进={improved_count}, 回归={regression_count}, 总计={len(comparison)}")
    if comparison:
        print(f"改进率: {improved_count/len(comparison)*100:.1f}%")


def run_test() -> None:
    """运行测试"""
    print("Phase3 对话归属 LLM 测试（使用真实数据）")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    client = AnnotationClient(task_type="annotation")
    print(f"Model: {client._config.model}")
    print(f"Base URL: {client._config.base_url}")
    print(f"Thinking: {client._config.thinking_enabled}")

    global_same = 0
    global_improved = 0
    global_regression = 0
    global_total = 0
    failed_chunks = []

    with get_session() as session:
        run_id = "14fddab9-c60b-4fc3-8265-029292eb7db3"
        chunk_repo = ChunkRepository(session)
        chunks = chunk_repo.fetch_chunk_texts(run_id)

        if not chunks:
            print(f"错误: 数据库中找不到 {run_id} 的 chunk 数据")
            return

        chunk_dict = dict(chunks)
        known_chars = get_known_characters_from_db(session, run_id)
        print(f"从数据库加载 {len(chunks)} 个 chunks")
        print(f"已知角色: {known_chars}")

        test_chunk_ids = list(sorted(chunk_dict.keys()))
        test_chunks = [(cid, chunk_dict[cid]) for cid in test_chunk_ids if cid in chunk_dict]

        if not test_chunks:
            print(f"错误: 数据库中找不到 chunk {test_chunk_ids}")
            return

        total_chunks = len(test_chunks)
        for idx, (chunk_id, text) in enumerate(test_chunks, 1):
            progress = f"[{idx}/{total_chunks}]"
            candidates = extract_dialogues_from_text(text, context_chars=50)
            old_results = get_old_results_from_db(session, chunk_id, run_id)

            start_time = time.time()
            try:
                result = compute_dialogue_lengths_with_llm(
                    client=client,
                    text=text,
                    alias_map=None,
                    chunk_id=chunk_id,
                    run_id="test-phase3-fix-20260331",
                    known_characters=known_chars,
                    return_tones=True,
                    return_evidences=True,
                    return_identity_clues=True,
                )
                duration = time.time() - start_time

                if len(result) == 6:
                    speaker_lengths, attribution, dialogues, tones, evidences, identity_clues = result
                elif len(result) == 5:
                    speaker_lengths, attribution, dialogues, tones, evidences = result
                    identity_clues = {}
                elif len(result) == 4:
                    speaker_lengths, attribution, dialogues, tones = result
                    evidences = {}
                    identity_clues = {}
                else:
                    speaker_lengths, attribution, dialogues = result
                    tones = {}
                    evidences = {}
                    identity_clues = {}

                records = []
                for didx, content in dialogues:
                    record = DialogueRecord(
                        index=didx,
                        content=content,
                        is_dialogue=True,
                        speaker=attribution.get(didx),
                        tone=tones.get(didx),
                        evidence=evidences.get(didx),
                        identity_clue=identity_clues.get(didx),
                    )
                    records.append(record)

                if old_results:
                    comparison = format_comparison(old_results, records, candidates)
                    chunk_same = sum(1 for c in comparison if c["is_same"])
                    chunk_improved = sum(1 for c in comparison if c["is_improved"])
                    chunk_regression = sum(1 for c in comparison if c["is_regression"])
                    chunk_total = len(comparison)
                    global_same += chunk_same
                    global_improved += chunk_improved
                    global_regression += chunk_regression
                    global_total += chunk_total
                    accuracy = chunk_same / chunk_total * 100 if chunk_total else 0
                    print(f"{progress} Chunk {chunk_id}: {chunk_total} dialogues, "
                          f"same={chunk_same}, improved={chunk_improved}, regression={chunk_regression}, "
                          f"accuracy={accuracy:.1f}%, time={duration:.1f}s")
                else:
                    global_total += len(dialogues)
                    print(f"{progress} Chunk {chunk_id}: {len(dialogues)} dialogues, "
                          f"no old results, time={duration:.1f}s")

            except Exception as e:
                duration = time.time() - start_time
                print(f"{progress} Chunk {chunk_id}: FAILED after {duration:.1f}s - {e}")
                import traceback
                traceback.print_exc()
                failed_chunks.append(chunk_id)

    # 全局统计
    print(f"\n{'='*80}")
    print("全局统计汇总")
    print(f"{'='*80}")
    print(f"总对话数: {global_total}")
    print(f"相同: {global_same} ({global_same/global_total*100:.1f}%)" if global_total else "")
    print(f"改进: {global_improved} ({global_improved/global_total*100:.1f}%)" if global_total else "")
    print(f"回归: {global_regression} ({global_regression/global_total*100:.1f}%)" if global_total else "")
    if failed_chunks:
        print(f"失败 chunks: {failed_chunks}")
    print(f"{'='*80}")
    print("测试完成")


if __name__ == "__main__":
    log_file = os.path.join(os.path.dirname(__file__), '_test_phase3_attribution_log.txt')
    with TeeLogger(log_file):
        run_test()