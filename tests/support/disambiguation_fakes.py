from __future__ import annotations

from types import SimpleNamespace

from src.models.local.disambiguation import (
    DisambiguationPromptContext,
    ExtendedDisambigResult,
    NameReviewState,
)
from src.rag import EvidenceBundle


def candidates(*names: str) -> list[dict[str, int | str]]:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 统一生成消歧候选输入，减少拆分后各测试文件重复造 dict。
    """
    return [{"name": name, "count": 1} for name in names]


class FakeDisambigClient:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 供消歧 pipeline 测试复用的轻量 client，记录关键入参而不触发模型调用。
    """

    def __init__(self) -> None:
        self._config = SimpleNamespace(model="test-model", thinking_enabled=True)
        self.received_existing_names: list[str] | None = None
        self.received_prompt_context: DisambiguationPromptContext | None = None
        self.received_reselect_clusters: list[list[str]] | None = None
        self.received_reselect_review_states: dict[str, NameReviewState] | None = None
        self.reselect_result = ExtendedDisambigResult(canonical_decisions={}, entity_types={}, entity_relations=[])

    async def disambiguate_characters(
        self,
        candidates,
        context_sentences=None,
        existing_names=None,
        prompt_context=None,
    ):
        self.received_existing_names = existing_names
        self.received_prompt_context = prompt_context
        return ExtendedDisambigResult(
            canonical_decisions={},
            entity_types={},
            entity_relations=[],
            _reasoning_tokens=17,
        )

    async def reselect_canonicals(
        self,
        candidates,
        clusters,
        context_sentences=None,
        review_states=None,
    ):
        self.received_reselect_clusters = [list(cluster) for cluster in clusters]
        self.received_reselect_review_states = dict(review_states or {})
        return self.reselect_result

    def is_cloud_api(self) -> bool:
        return False


class FakeNarrativeEvidenceService:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 复用 RAG evidence provider 假实现，显式记录 level1/2 与 level3 收集参数。
    """

    def __init__(
        self,
        bundle: EvidenceBundle,
        *,
        level3_available: bool = True,
        requires_level3: bool = False,
    ) -> None:
        self.bundle = bundle
        self.level3_available = level3_available
        self._requires_level3 = requires_level3
        self.calls: list[dict] = []

    def requires_level3(self) -> bool:
        return self._requires_level3

    def is_level3_available(self) -> bool:
        return self.level3_available

    async def collect(self, request):
        """
        修改时间: 2026-04-23
        任务: level3-history-cutoff
        修改说明: 测试假实现记录 max_chunk_id，便于断言共享证据链的历史边界。

        修改时间: 2026-04-23
        任务: level3-mention-retrieval
        修改说明: 记录 mention_queries，便于测试确认 mention 检索链路已接入。

        修改时间: 2026-04-25
        任务: evidence-service-request-unification
        修改说明: service 统一改为 collect(request)；假实现同步记录 consumer/requested_names/seed_entities/
                  background_entities/need_level*，便于测试真实输入合同是否收口。
        """
        self.calls.append(
            {
                "method": "collect",
                "request": request,
                "consumer": request.consumer,
                "objective": request.objective,
                "requested_names": list(request.requested_names),
                "names_in_chunk": list(request.seed_entities),
                "background_entities": list(request.background_entities),
                "current_chunk": request.current_chunk,
                "context_text": request.query_text,
                "exclude_chunk_ids": list(request.exclude_chunk_ids),
                "max_chunk_id": request.max_chunk_id,
                "max_queries": request.max_queries,
                "need_level1": request.need_level1,
                "need_level2": request.need_level2,
                "need_level3": request.need_level3,
            }
        )
        if request.need_level3 and self._requires_level3 and not self.level3_available:
            raise RuntimeError("Level 3 vector retrieval is required but not available")
        return self.bundle
