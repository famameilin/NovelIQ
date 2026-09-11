"""章内并行两段式：读者消息池（设计文档《章内并行设计-子代理只读顾问与主代理单写者》§5/§12）

消息是带逐字证据的结构化观察：读者经 send_message 入池，写者消费。
消息不落业务表（审计经 agent_tool_calls 的 send_message 入参天然留痕），
池本身是章级内存对象，随章事务生命周期消亡。
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any

MESSAGE_KINDS = (
    "metric",
    "entity",
    "event_tree",
    "dialogue",
    "sentence_label",
    "relation",
    "case",
    "note",
)
_MESSAGE_KINDS_SET = frozenset(MESSAGE_KINDS)

# 2026-09-11 用户裁决"上报不设上限"：消息条数/长度均不设预算，
# 唯一硬约束是证据引文必须能在段落内唯一命中（服务端 fail-fast 校验）


def normalize_message_name(name: str) -> str:
    """2026-09-11 用于生成与实体目录一致的名称匹配键（NFC + strip + casefold）"""
    return unicodedata.normalize("NFC", name).strip().casefold()


class MessagePoolError(ValueError):
    """2026-09-11 用于标记 send_message 校验失败（消息不入池，读者会话内自纠）"""


@dataclass(slots=True)
class ReaderMessage:
    """单条读者观察消息（§5.1）"""

    message_id: int
    # 0 基子块序号；展示面（writer_view / ask_reader.block）用 1 基
    block_index: int
    kind: str
    summary: str
    payload: dict[str, Any]
    evidence: list[dict[str, Any]] = field(default_factory=list)
    # dialogue 专属：候选序号按章级候选表解析后的序号（跨块无法解析时为 None）
    chapter_candidate_index: int | None = None


class ReaderMessagePool:
    """章级消息池：读者并发追加，写者按 (block_index, message_id) 消费（§8.2 确定性）

    排序与读者完成顺序无关：先按块序、块内按入池序，打乱完成时序不改变写者输入。
    """

    def __init__(self) -> None:
        self._messages: list[ReaderMessage] = []
        self._next_id = 1

    def append(
        self,
        *,
        block_index: int,
        kind: str,
        summary: str,
        payload: dict[str, Any],
        evidence: list[dict[str, Any]],
        chapter_candidate_index: int | None = None,
    ) -> ReaderMessage:
        if kind not in _MESSAGE_KINDS_SET:
            raise ValueError(f"未知消息 kind: {kind}")
        message = ReaderMessage(
            message_id=self._next_id,
            block_index=block_index,
            kind=kind,
            summary=summary,
            payload=payload,
            evidence=evidence,
            chapter_candidate_index=chapter_candidate_index,
        )
        self._next_id += 1
        self._messages.append(message)
        return message

    def discard_block(self, block_index: int) -> None:
        """2026-09-11 用于读者会话级重试前清空该块旧消息（重跑读者从零上报）"""
        self._messages = [message for message in self._messages if message.block_index != block_index]

    def ordered(self) -> list[ReaderMessage]:
        return sorted(self._messages, key=lambda message: (message.block_index, message.message_id))

    def message_count(self) -> int:
        return len(self._messages)

    def messages_since(self, message_id: int) -> list[ReaderMessage]:
        """2026-09-11 用于 ask_reader 回执：取该 id 之后新入池的消息（按池序）"""
        return [message for message in self.ordered() if message.message_id > message_id]

    def max_message_id(self) -> int:
        return self._next_id - 1

    def message_ids(self) -> list[int]:
        return [message.message_id for message in self.ordered()]

    def writer_view(self) -> str:
        """2026-09-11 用于把消息池渲染进写者首条请求的 <ReaderMessages> 块（§12 消息池快照）"""
        lines: list[str] = []
        for message in self.ordered():
            evidence_text = "；".join(
                f'¶{evidence.get("paragraph_id")} "{evidence.get("quote")}"' for evidence in message.evidence
            )
            payload = dict(message.payload)
            if message.kind == "dialogue" and message.chapter_candidate_index is not None:
                payload["chapter_candidate_index"] = message.chapter_candidate_index
            lines.append(
                f'<message id="{message.message_id}" block="{message.block_index + 1}" kind="{message.kind}">\n'
                f"summary: {message.summary}\n"
                f"payload: {json.dumps(payload, ensure_ascii=False)}\n"
                f"evidence: {evidence_text}\n"
                f"</message>"
            )
        return "\n".join(lines)

    def entity_name_keys(self) -> set[str]:
        """2026-09-11 用于写者取值域准入（§7）：消息池中陈述过的实体名集合"""
        keys: set[str] = set()
        for message in self._messages:
            payload = message.payload
            if message.kind == "entity":
                name = payload.get("name")
                if isinstance(name, str) and name.strip():
                    keys.add(normalize_message_name(name))
            elif message.kind == "event_tree":
                for participant in payload.get("participants") or []:
                    if isinstance(participant, dict) and isinstance(participant.get("entity"), str):
                        keys.add(normalize_message_name(participant["entity"]))
                for child in payload.get("children") or []:
                    if not isinstance(child, dict):
                        continue
                    for participant in child.get("participants") or []:
                        if isinstance(participant, dict) and isinstance(participant.get("entity"), str):
                            keys.add(normalize_message_name(participant["entity"]))
            elif message.kind == "relation":
                for endpoint in ("from_entity", "to_entity"):
                    name = payload.get(endpoint)
                    if isinstance(name, str) and name.strip():
                        keys.add(normalize_message_name(name))
            elif message.kind == "dialogue":
                speaker = payload.get("speaker")
                if isinstance(speaker, str) and speaker.strip():
                    keys.add(normalize_message_name(speaker))
            elif message.kind == "case":
                for name in payload.get("entities") or []:
                    if isinstance(name, str) and name.strip():
                        keys.add(normalize_message_name(name))
        return keys

    def case_quotes(self) -> tuple[str, ...]:
        """2026-09-11 用于写者案例裁决准入（§7）：case 消息的逐字引文集合"""
        return tuple(
            unicodedata.normalize("NFC", str(evidence.get("quote") or ""))
            for message in self._messages
            if message.kind == "case"
            for evidence in message.evidence
            if evidence.get("quote")
        )


__all__ = [
    "MESSAGE_KINDS",
    "MessagePoolError",
    "ReaderMessage",
    "ReaderMessagePool",
    "normalize_message_name",
]
