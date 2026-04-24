# 统一项目级结构化输出适配层与 Instructor 接入规划

创建时间: 2026-04-24
任务: structured-output-adapter-instructor-unification
说明: 规划项目级结构化输出适配层，统一 json_schema / json_object / Instructor 的调用入口，
      避免 annotation、disambiguation、diagnosis、RAG 增强链路各自处理 provider 差异。

## 背景

当前项目已经有多条结构化输出链路：

- annotation Phase2/3/4：`ForeshadowingResult`、`DialogueAttributionResult`、`RelationExtractionResult`
- incremental/full disambiguation：`DisambiguateResponseModel` / `CloudDisambiguateResponseModel`
- diagnosis：`CloudAnalysis`
- RAG mention extraction：`LLMPersonMentionCloudResponse`
- RAG Level3 rerank：`LLMLevel3RerankResponse`

现状里，本地和部分 OpenAI-compatible 服务商可以接受 strict `response_format={"type":"json_schema"}`。
但 DeepSeek 当前文档要求使用 `response_format={"type":"json_object"}`，并在 prompt 中显式包含 `json` 与输出样例。
本分支已经先为 `mention_extraction` 做了局部兼容：云端走 `json_object`，返回后继续用 Pydantic 校验。

这个问题不是 mention extraction 独有。只要后续 annotation / disambiguation / diagnosis / rerank 切到只支持
`json_object` 的服务商，同类问题会再次出现。

## Git 历史结论

仓库历史里曾集成过 Instructor，但后来移除或弱化：

- `dffd400`：云端消歧存在 `_call_with_instructor()`，失败后 fallback 到传统解析；annotation 也有 Instructor 客户端相关痕迹。
- `e5465c3`：删除 annotation 中废弃的 `_get_instructor_client()`，注释里写明“移除 Instructor 依赖”。
- `90acd4e`：disambiguation 拆分后的注释记录了“2026-03-16 使用 Instructor，2026-03-17 改为 JSON Schema”。
- `619ab20`：提交主题为保留统一模型客户端架构并恢复 disambiguation 行为，将调用收口到 `BaseModelClient`。

据此判断：当时 Instructor 并非因能力不可用而被放弃，主要原因是它容易绕开项目统一的 transport、streaming、thinking、
token_usage、model_interactions 审计与 fallback 语义。

2026-04-24 重新实测：

- `Instructor + Mode.JSON + DeepSeek` 可以解析 Pydantic response model。
- 使用 `create_with_completion()` 可以拿回原始 `ChatCompletion`，仍可提取 thinking 与 reasoning tokens。
- 因此 Instructor 可以作为底层能力，但不应裸露给各业务模块直接使用。

## 目标

建立一个项目级结构化输出适配层，让所有模型结构化调用统一经过同一个入口：

- provider 支持 strict `json_schema` 时，继续使用现有 strict schema。
- provider 只支持 `json_object` 时，使用 JSON Output，并在本地继续 Pydantic 校验。
- 如需使用 Instructor，应封装在适配层内部，不让业务模块感知 Instructor。
- 保留现有 `BaseModelClient` 作为唯一运行时入口，不能重开一条绕过审计和 token 账本的 transport。

## 非目标

- 不在各模块里重复判断 `DeepSeek` / `json_object` / `Instructor`。
- 不把 Instructor 直接扩散到 annotation、disambiguation、diagnosis、RAG 业务代码。
- 不降低内部结构化合同。即使 provider 只保证合法 JSON，项目仍必须用 Pydantic 校验。
- 不在本阶段重构 SSE。structured output 的非流式/流式统一可以后续单列。

## 建议架构

新增一个结构化输出适配模块，例如：

```text
src/models/structured_output/
  __init__.py
  adapter.py
  modes.py
  provider_capabilities.py
  instructor_adapter.py
```

核心 DTO：

```python
@dataclass(frozen=True)
class StructuredOutputRequest[T: BaseModel]:
    messages: list[dict[str, str]]
    response_model: type[T]
    call_type: str
    enable_thinking: bool
    timeout: float | None = None
    json_output_prompt_hint: str | None = None
```

```python
@dataclass(frozen=True)
class StructuredOutputResult[T: BaseModel]:
    parsed: T
    raw_response: Any
    response_text: str
    thinking_content: str | None
    reasoning_tokens: int | None
    mode: Literal["json_schema", "json_object", "instructor_json"]
```

核心入口：

```python
async def call_structured_output(
    client: BaseModelClient,
    request: StructuredOutputRequest[T],
) -> StructuredOutputResult[T]:
    ...
```

业务层只关心：

- 传入 `messages`
- 传入 `response_model`
- 得到 `parsed`
- 用 `raw_response / response_text / thinking_content / reasoning_tokens` 做现有审计

## Mode 选择策略

初版建议按配置与能力判断：

1. 本地服务或已知支持 strict schema 的服务：`json_schema`
2. DeepSeek 这类只支持 JSON Output 的服务：`json_object`
3. 需要 Instructor 修复 provider JSON 兼容差异时：`instructor_json`

不要在业务代码里硬编码 base_url 字符串。可以先用最小配置字段，例如：

```json
{
  "structured_output": {
    "annotation": "json_schema",
    "annotation_fallback": "json_object",
    "incremental_disambig": "json_schema",
    "mention_extraction": "json_object",
    "level3_rerank": "json_schema",
    "diagnosis": "json_schema"
  }
}
```

如果暂时不增加 settings 字段，也至少应在 `provider_capabilities.py` 集中判断，避免散落到业务模块。

## Prompt 合同

`json_schema` 模式下：

- 可继续依赖 `response_format={"type":"json_schema", ...}`。
- prompt 不一定要给完整 JSON 样例，但建议保留关键格式说明。

`json_object` / `instructor_json` 模式下：

- system 或 user prompt 必须包含 `json` 字样。
- prompt 必须给出符合 response model 的 JSON 示例。
- 需要设置足够 `max_tokens`，避免 JSON 被截断。
- 如果返回空 content，必须显式报错并进入现有 retry/fallback，不允许静默吞掉。

## 审计与 token 账本

适配层必须返回 raw response，而不是只返回 Pydantic 对象。

原因：

- `model_interactions` 需要 prompt、response、thinking、reasoning tokens、duration、status。
- `token_usage` 需要基于 prompt/response 估算。
- parse 失败但 response 已返回时，也要补记 token。
- Instructor 只能通过 `create_with_completion()` 这类接口接入，确保 raw completion 不丢。

审计落库仍放在各现有 runtime/audit helper 中，适配层只负责“调用 + 解析 + 提取响应元信息”。

## 迁移范围

第一阶段：抽公共能力，不改主业务语义。

- 将 `BaseModelClient._call_api(... raw_response_format=...)` 下沉到适配层消费。
- 把 `mention_extraction` 现有 `json_object` 特判迁入适配层。
- 保持 `level3_rerank` 继续走 `json_schema`。
- 增加 `StructuredOutputResult` 单测。

第二阶段：接入 RAG 两条增强链。

- `LLMPersonMentionExtractor` 改用 `call_structured_output()`。
- `LLMLevel3Reranker` 改用 `call_structured_output()`。
- 复用现有 `model_call_audit.py`，不改变审计字段。

第三阶段：迁移 annotation / disambiguation / diagnosis。

- annotation `_call_annotation_api()` 使用适配层。
- disambiguation `call_disambiguate_api()` 使用适配层，同时保留 cloud-safe schema。
- diagnosis `_diagnose_once()` 使用适配层。
- 保留 streaming/SSE 行为时需要特别谨慎，避免破坏当前云端 stream 输出。

## 测试计划

单元测试：

- `json_schema` mode 会传 strict schema。
- `json_object` mode 会传 `{"type": "json_object"}` 并用 Pydantic 校验。
- `instructor_json` mode 使用 `create_with_completion()`，返回 parsed 与 raw completion。
- provider 返回空 content 时抛错。
- provider 返回非法 JSON 时抛错。
- provider 返回 JSON 但不符合 Pydantic schema 时抛错。
- parse 失败但 raw response 存在时，调用方仍能补记 token。

集成/真实 provider 探针：

- DeepSeek mention extraction：`json_object` 通过。
- 本地 qwen rerank：`json_schema` 通过。
- DeepSeek Instructor JSON probe：可解析，并能拿到 thinking/reasoning。

回归测试：

- `tests/rag/test_mention_retrieval.py`
- `tests/models/test_base_model_client_contracts.py`
- `tests/models/test_structured_output_schema.py`
- `tests/workflows/annotate_helpers/test_context.py`

## 风险

- Instructor 默认可能会重试或改写 prompt，需要确认是否影响现有 retry 语义。
- Instructor 可能在不同 mode 下使用 tool calling / json mode，不同 provider 支持度不同。
- 流式响应与 Instructor 的组合不应在本阶段强行合并。
- `json_object` 只保证合法 JSON，不保证 schema，必须依赖 Pydantic 校验与 retry/fallback。
- 如果把 mode 判断散落到业务代码，会重新制造历史上的多通道复杂度。

## 建议结论

应推进“统一项目级结构化输出适配层”，并允许在适配层内部使用 Instructor。

但落地原则必须是：

- 业务模块不直接 import Instructor。
- `BaseModelClient` 仍是模型运行时上下文入口。
- 适配层返回 raw response，审计与 token 账本不丢。
- provider 差异集中处理。
- 先迁移 RAG mention/rerank，再迁移 annotation/disambiguation/diagnosis。
