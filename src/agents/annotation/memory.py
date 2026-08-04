"""
标注 Agent 身份记忆

跨 chunk 维护角色身份状态（消歧集成进 agent 循环的载体）：
- known_canonical_names: 已确认的规范名
- alias_map: 表面称呼 → 规范名
- entity_types: 规范名 → 实体类型
- discovered_names: 已见过的称呼

持久化复用 disambig_checkpoint 表（run_id → JSON 快照），支持 resume
"""

from __future__ import annotations

import json
import time

from loguru import logger
from sqlalchemy import text


class IdentityMemory:
    """角色身份记忆"""

    def __init__(
        self,
        *,
        known_canonical_names: set[str] | None = None,
        alias_map: dict[str, str] | None = None,
        entity_types: dict[str, str] | None = None,
        discovered_names: set[str] | None = None,
    ) -> None:
        self.known_canonical_names: set[str] = known_canonical_names or set()
        self.alias_map: dict[str, str] = alias_map or {}
        self.entity_types: dict[str, str] = entity_types or {}
        self.discovered_names: set[str] = discovered_names or set()

    def apply_decisions(self, decisions: list[dict]) -> None:
        """
        应用 agent 的身份消歧决策（merge 到记忆）

        decisions 结构: [{name, canonical, entity_type, confidence, evidence}]
        """
        for decision in decisions:
            # 低置信度仅作为当前块候选，不能写入跨 chunk 的确认身份记忆
            if str(decision.get("confidence") or "").strip().lower() == "low":
                continue
            name = str(decision.get("name") or "").strip()
            canonical = str(decision.get("canonical") or "").strip()
            if not name or not canonical:
                continue
            self.discovered_names.add(name)
            if name == canonical:
                self.known_canonical_names.add(name)
                self.alias_map.pop(name, None)
            else:
                self.known_canonical_names.add(canonical)
                self.alias_map[name] = canonical
                self.discovered_names.add(canonical)
            entity_type = str(decision.get("entity_type") or "").strip() or "character"
            if canonical:
                self.entity_types[canonical] = entity_type

    def to_dict(self) -> dict:
        return {
            "known_canonical_names": sorted(self.known_canonical_names),
            "alias_map": dict(self.alias_map),
            "entity_types": dict(self.entity_types),
            "discovered_names": sorted(self.discovered_names),
        }

    @classmethod
    def from_dict(cls, data: dict) -> IdentityMemory:
        return cls(
            known_canonical_names=set(data.get("known_canonical_names") or []),
            alias_map=dict(data.get("alias_map") or {}),
            entity_types=dict(data.get("entity_types") or {}),
            discovered_names=set(data.get("discovered_names") or []),
        )

    def to_state_dict(self) -> dict:
        """给 agent state 的序列化视图（可 JSON 传递）"""
        return self.to_dict()

    @classmethod
    def from_state_dict(cls, data: dict) -> IdentityMemory:
        return cls.from_dict(data)


def load_identity_memory(conn, run_id: str) -> IdentityMemory:
    """从数据库加载身份记忆快照（不存在则返回空记忆）"""
    result = conn.execute(
        text("SELECT state_json FROM disambig_checkpoint WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchone()

    if not result or not result._mapping["state_json"]:
        return IdentityMemory()

    try:
        raw_data = json.loads(result._mapping["state_json"])
    except json.JSONDecodeError:
        logger.warning("invalid identity memory JSON for run_id={}", run_id)
        return IdentityMemory()

    if not isinstance(raw_data, dict) or "alias_map" not in raw_data:
        logger.warning("invalid identity memory shape for run_id={}", run_id)
        return IdentityMemory()

    memory = IdentityMemory.from_dict(raw_data)
    logger.info(
        "identity memory loaded: run_id={} canonicals={} aliases={}",
        run_id,
        len(memory.known_canonical_names),
        len(memory.alias_map),
    )
    return memory


def save_identity_memory(conn, run_id: str, memory: IdentityMemory) -> None:
    """保存身份记忆检查点到数据库（upsert）"""
    conn.execute(
        text("""
        INSERT INTO disambig_checkpoint (run_id, state_json, updated_at)
        VALUES (:run_id, :state_json, :updated_at)
        ON CONFLICT (run_id) DO UPDATE SET
            state_json = EXCLUDED.state_json,
            updated_at = EXCLUDED.updated_at
    """),
        {
            "run_id": run_id,
            "state_json": json.dumps(memory.to_dict(), ensure_ascii=False),
            "updated_at": time.time(),
        },
    )
    conn.commit()
    logger.debug(
        "identity memory saved: run_id={} canonicals={} aliases={}",
        run_id,
        len(memory.known_canonical_names),
        len(memory.alias_map),
    )
