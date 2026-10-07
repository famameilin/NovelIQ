"""对话候选判定与实际读取证据授权；不持有队列、模型会话或保存事务"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import DialogueCandidate, DialogueInput
from src.fact_graph.outputs import BoundDialogue
from src.fact_graph.vocabulary import DialogueVerdict, Tone

from .errors import (
    AnnotationStageRejection,
)
from .validation_errors import _translate_record_validation


class DialogueEvidenceStateContext(Protocol):
    """只开放此工作状态需要的上下文和引用能力"""

    def _require_writable(self, record: str) -> None: ...

    graph: FactGraph | None

    def resolve_entity_ref(self, ref: str, *, record: str, field: str) -> str: ...


@dataclass(slots=True)
class DialogueEvidenceState:
    dialogue_candidates: list[DialogueCandidate] = field(default_factory=list)
    written_dialogues: dict[int, DialogueInput] = field(default_factory=dict)
    authorized_text_paragraph_ids: set[int] = field(default_factory=set)
    text_references: dict[str, Any] = field(default_factory=dict)
    source_anchors: dict[str, list[Any]] = field(default_factory=dict)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)

    def apply_dialogue(
        self,
        ctx: DialogueEvidenceStateContext,
        *,
        candidate_index: int,
        verdict: DialogueVerdict,
        speaker_ref: str | None,
        tone: Tone | None,
    ) -> str:
        """用于按候选序号写入一条对话三态判断（同序号重写按更新语义）"""
        record = f"dialogue/{candidate_index}"
        ctx._require_writable(record)
        candidate_by_index = dict(enumerate(self.dialogue_candidates, start=1))
        if candidate_index not in candidate_by_index:
            raise AnnotationStageRejection(
                f"candidate_index 超出系统候选范围: {candidate_index}",
                record=record,
                field="candidate_index",
                code="out_of_range",
                expected=f"1..{len(self.dialogue_candidates)}（见正文后的 DialogueCandidates 表）",
            )
        speaker_name: str | None = None
        if speaker_ref is not None:
            speaker_name = ctx.resolve_entity_ref(speaker_ref, record=record, field="speaker")
            if ctx.graph is not None and ctx.graph.entity_type(speaker_name) != "character":
                raise AnnotationStageRejection(
                    f"说话人必须是 character: {speaker_name}",
                    record=record,
                    field="speaker",
                    code="not_character",
                    expected="character 类型的实体（run 级 id 或 el 键）",
                )
        try:
            item = DialogueInput(
                candidate_index=candidate_index,
                verdict=verdict,
                speaker=speaker_name,
                tone=tone,
            )
        except ValidationError as exc:
            raise _translate_record_validation(record, exc, tool_name="write_dialogue") from None
        self.written_dialogues[candidate_index] = item
        self._rebuild_dialogue_payload()
        return record

    def _rebuild_dialogue_payload(self) -> None:
        """用于按候选序重建对话载荷（判定表 + 仅含真对话/独白的落账视图）"""
        candidate_by_index = dict(enumerate(self.dialogue_candidates, start=1))
        items = [self.written_dialogues[index] for index in sorted(self.written_dialogues)]
        bound: list[BoundDialogue] = []
        for item in items:
            if item.verdict == DialogueVerdict.NOT_DIALOGUE:
                continue
            candidate = candidate_by_index[item.candidate_index]
            bound.append(
                BoundDialogue(
                    candidate_index=item.candidate_index,
                    candidate_key=candidate.candidate_key,
                    content=candidate.content,
                    start=candidate.start,
                    end=candidate.end,
                    speaker=item.speaker,
                    tone=item.tone,
                    is_inner_monologue=item.verdict == DialogueVerdict.INNER_MONOLOGUE,
                )
            )
        self.domain_payloads["dialogues"] = items
        self.bound_payloads["dialogues"] = bound

    def dialogue_content(self, candidate_index: int) -> dict[str, Any]:
        """用于回显 write_dialogue 后该候选的生效判定（speaker 已解析为登记名，带 candidate_key）"""
        content = self.written_dialogues[candidate_index].model_dump(mode="json")
        content["candidate_key"] = self.dialogue_candidates[candidate_index - 1].candidate_key
        return content

    def dialogue_ledger(self) -> dict[str, Any]:
        """用于对话域账本：候选总数/已判定写入数/未写入编号 + 已判条目的判定值

        judged 带值是对抗整册重推的关键：只报"已判 N/M"时模型把未判清单读成
        "一切从零重推"，写完的条目也要回文核对（run b7477080 ch1 全册过 6 遍）。
        """
        judged: dict[str, str] = {}
        for index, item in sorted(self.written_dialogues.items()):
            if str(item.verdict) != "dialogue":
                judged[str(index)] = str(item.verdict)
            else:
                judged[str(index)] = f"{item.speaker or 'null'}/{item.tone or 'null'}"
        pending = sorted(set(range(1, len(self.dialogue_candidates) + 1)) - set(self.written_dialogues))
        return {
            "total": len(self.dialogue_candidates),
            "written": len(self.written_dialogues),
            "pending": pending,
            "judged": judged,
        }
