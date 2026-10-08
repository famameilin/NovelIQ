"""固定输入的完整查询契约；只规范化明确的运行时字段"""

from __future__ import annotations

import asyncio
import json
import uuid
from itertools import count
from pathlib import Path
from typing import Any

ENDPOINTS = (
    "pipeline",
    "tabs/dashboard",
    "graph",
    "event-forest",
    "timeline",
    "topics",
    "topics/aggregate",
    "topics/series",
    "diagnosis",
    "graph/metrics",
    "results",
)


def prepare_scenario(session: Any, monkeypatch: Any) -> Any:
    """身份和模型训练种子固定，前后版本读取同一份提交后的记录与模型产物"""
    from src.config import settings
    from src.metrics.queries.global_stats import save_global_stats
    from src.workflows.topic import run_topic_model
    from tests.support import chapter_annotation_helpers
    from tests.support.chapter_annotation_helpers import relation_fact
    from tests.support.timeline_contract_helpers import create_timeline_contract_scenario

    sequence = count()
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.uuid5(uuid.NAMESPACE_URL, f"module-contract:{next(sequence)}"))
    monkeypatch.setattr(chapter_annotation_helpers, "uuid4", uuid.uuid4)
    scenario = create_timeline_contract_scenario(
        session,
        # 最终保留三角人物关系，避开旧版本空图故障及二分图 HITS 重根
        final_relations=[
            relation_fact(chapter_id=5, from_name=left, to_name=right, relation_type="友情")
            for left, right in [("顾承渊", "苏映雪"), ("顾承渊", "陆遥"), ("苏映雪", "陆遥")]
        ],
        events_by_chapter={
            1: [
                {
                    "description": "顾承渊踏入江湖",
                    "evidence_paragraph_id": 0,
                    "node_id": "arch-root",
                    "tree_id": "arrival",
                    "cause_role": "root",
                    "isforeshadowing": True,
                    "payoff_likelihood": "high",
                },
                {
                    "description": "顾承渊记下线索",
                    "evidence_paragraph_id": 0,
                    "node_id": "arch-main",
                    "tree_id": "arrival",
                    "parent_node_id": "arch-root",
                    "cause_role": "main",
                },
                {
                    "description": "顾承渊检查石碑",
                    "evidence_paragraph_id": 0,
                    "node_id": "arch-side",
                    "tree_id": "arrival",
                    "parent_node_id": "arch-root",
                    "cause_role": "secondary",
                },
            ],
            2: [
                {
                    "description": "苏映雪现身同行",
                    "evidence_paragraph_id": 1,
                    "node_id": "arch-second",
                    "tree_id": "companion",
                    "cause_role": "root",
                }
            ],
        },
    )
    monkeypatch.setattr(settings.topic_model, "min_paragraph_train_tokens", 1)
    asyncio.run(run_topic_model(scenario.run_id, session, num_topics=2, passes=1, iterations=10, force=True))
    save_global_stats(session, scenario.run_id)
    session.commit()
    return scenario


def capture(client: Any, novel_id: str, task_id: str) -> dict[str, Any]:
    """捕获完整响应和实际导出文件，不以部分字段断言代替结果对照"""
    import json

    result = {}
    for endpoint in ENDPOINTS:
        params: dict[str, str | int] = {"task_id": task_id}
        response = client.get(f"/api/novels/{novel_id}/{endpoint}", params=params)
        assert response.status_code == 200, f"{endpoint}: {response.text}"
        result[endpoint] = response.json()
    result["export"] = json.loads(Path(result["results"]["file_path"]).read_text(encoding="utf-8"))
    return result


def normalize(value: Any, path: tuple[str, ...] = (), *, stable_collections: bool = True) -> Any:
    """运行字段按路径屏蔽；仅两处无序关系集合规范化，有序业务数据不排序"""
    if path in {("results", "file_path"), ("export", "generated_at")}:
        return "<runtime>"
    if isinstance(value, dict):
        return {
            key: normalize(item, (*path, key), stable_collections=stable_collections) for key, item in value.items()
        }
    if isinstance(value, list):
        if stable_collections and path in {("graph", "edges"), ("export", "character_relations")}:
            value = sorted(value, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
        return [
            normalize(item, (*path, str(index)), stable_collections=stable_collections)
            for index, item in enumerate(value)
        ]
    return value


def differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    """输出精确字段路径，完整快照差异可直接定位且不会隐藏数组排序变化"""
    if isinstance(expected, dict) and isinstance(actual, dict):
        if expected.keys() != actual.keys():
            return [f"{path}: 字段集合不同"]
        return [diff for key in expected for diff in differences(expected[key], actual[key], f"{path}/{key}")]
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}: 长度 {len(expected)} != {len(actual)}"]
        return [
            diff
            for index, (left, right) in enumerate(zip(expected, actual, strict=True))
            for diff in differences(left, right, f"{path}/{index}")
        ]
    return [] if expected == actual else [f"{path}: {expected!r} != {actual!r}"]
