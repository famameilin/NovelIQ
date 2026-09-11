"""可调设置字段注册表（schema 驱动表单的单一事实源）

2026-09-10 设置模块重设计：所有可通过设置页编辑的参数在此静态声明，
前端按注册表自动渲染表单，后端按注册表计算来源与写回稀疏文件。
默认值不在此声明——唯一事实源是 src/config/schemas/ 的 dataclass 默认值，
经 Settings 序列化在响应中合并输出（tests/config/test_settings_registry.py
做注册表↔dataclass 双向校验，防止漂移）。

凭据字段（base_url/model/api_key）不在注册表：它们只存 .env，
由设置页的 .env 编辑器通道单独处理。
日志（logging）与存储路径（paths）是运营配置而非用户可调参数，
同样不进注册表：settings.json 中的现存值照常生效，但不在设置页露出
（2026-09-10 用户裁决）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SettingFieldType = Literal["number", "integer", "boolean", "enum", "string"]

SETTING_FIELD_TYPES = ("number", "integer", "boolean", "enum", "string")


@dataclass(frozen=True)
class SettingSectionSpec:
    """设置分组元数据（前端渲染为一个分区卡片）"""

    id: str
    title: str
    description: str = ""
    order: int = 0


@dataclass(frozen=True)
class SettingFieldSpec:
    """单个可调参数的声明

    path: 结构化路径（settings.json 中的嵌套位置）
    """

    path: tuple[str, ...]
    field_type: SettingFieldType
    label: str
    description: str = ""
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    enum_values: tuple[str, ...] = ()
    nullable: bool = False
    # 非可编辑字段（如建库维度类参数）不渲染输入控件也不提供恢复默认；
    # 当前注册表已无可编辑=False 的字段（embedding_dim 配置链 2026-09-10 删除），
    # 机制保留作通用能力
    editable: bool = True


SETTING_SECTIONS: tuple[SettingSectionSpec, ...] = (
    SettingSectionSpec(id="models", title="模型参数", description="标注/诊断任务与段落嵌入的运行参数", order=1),
    SettingSectionSpec(id="topic_model", title="主题模型", description="LDA 训练与主题变化候选参数", order=2),
    SettingSectionSpec(id="metrics", title="指标计算", description="各量化指标的阈值与采样参数", order=3),
    SettingSectionSpec(id="linguistic", title="语言特征", description="LTP 与 Word2Vec 能力开关及参数", order=4),
)


def _fields(specs: list[SettingFieldSpec]) -> list[SettingFieldSpec]:
    return specs


MODEL_ENV_KEYS: frozenset[str] = frozenset(
    {
        "MODEL_BASE_URL",
        "MODEL_ID",
        "MODEL_KEY",
        "EMBEDDING_MODEL_BASE_URL",
        "EMBEDDING_MODEL_ID",
        "EMBEDDING_MODEL_KEY",
        "LTP_MODEL_DIR",
    }
)

SETTING_FIELDS: tuple[SettingFieldSpec, ...] = tuple(
    _fields(
        [
            # ---- models.annotation（标注任务）----
            SettingFieldSpec(
                path=("models", "annotation", "timeout_s"),
                field_type="number",
                label="标注超时（秒）",
                min_value=1,
                nullable=True,
            ),
            SettingFieldSpec(
                path=("models", "annotation", "temperature"),
                field_type="number",
                label="标注温度",
                min_value=0,
                max_value=2,
                step=0.1,
            ),
            SettingFieldSpec(
                path=("models", "annotation", "top_p"),
                field_type="number",
                label="标注 top_p",
                min_value=0,
                max_value=1,
                step=0.05,
            ),
            SettingFieldSpec(path=("models", "annotation", "thinking"), field_type="boolean", label="标注思考模式"),
            SettingFieldSpec(path=("models", "annotation", "streaming"), field_type="boolean", label="标注流式输出"),
            SettingFieldSpec(
                path=("models", "annotation", "structured_output"),
                field_type="enum",
                label="结构化输出模式",
                enum_values=("json_schema", "json_object"),
            ),
            SettingFieldSpec(
                path=("models", "annotation", "max_iterations"),
                field_type="integer",
                label="标注最大回合数",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("models", "annotation", "total_attempts"),
                field_type="integer",
                label="标注总尝试次数",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("models", "annotation", "allow_future_context"),
                field_type="boolean",
                label="允许读取未来文本",
            ),
            # ---- models.diagnosis（诊断任务）----
            SettingFieldSpec(
                path=("models", "diagnosis", "timeout_s"),
                field_type="number",
                label="诊断超时（秒）",
                min_value=1,
                nullable=True,
            ),
            SettingFieldSpec(
                path=("models", "diagnosis", "temperature"),
                field_type="number",
                label="诊断温度",
                min_value=0,
                max_value=2,
                step=0.1,
            ),
            SettingFieldSpec(
                path=("models", "diagnosis", "top_p"),
                field_type="number",
                label="诊断 top_p",
                min_value=0,
                max_value=1,
                step=0.05,
            ),
            SettingFieldSpec(path=("models", "diagnosis", "thinking"), field_type="boolean", label="诊断思考模式"),
            SettingFieldSpec(path=("models", "diagnosis", "streaming"), field_type="boolean", label="诊断流式输出"),
            SettingFieldSpec(
                path=("models", "diagnosis", "structured_output"),
                field_type="enum",
                label="诊断结构化输出模式",
                enum_values=("json_schema", "json_object"),
            ),
            SettingFieldSpec(
                path=("models", "diagnosis", "max_iterations"),
                field_type="integer",
                label="诊断最大回合数",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("models", "diagnosis", "total_attempts"),
                field_type="integer",
                label="诊断总尝试次数",
                min_value=1,
            ),
            # ---- models.paragraph_embedding（段落嵌入）----
            SettingFieldSpec(
                path=("models", "paragraph_embedding", "timeout_s"),
                field_type="number",
                label="嵌入超时（秒）",
                min_value=1,
                nullable=True,
            ),
            SettingFieldSpec(
                path=("models", "paragraph_embedding", "batch_size"),
                field_type="integer",
                label="嵌入批大小",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("models", "paragraph_embedding", "semantic_enabled"),
                field_type="boolean",
                label="启用语义检索",
            ),
            SettingFieldSpec(
                path=("models", "paragraph_embedding", "top_k"),
                field_type="integer",
                label="语义召回条数",
                min_value=1,
            ),
            # ---- topic_model ----
            SettingFieldSpec(path=("topic_model", "num_topics"), field_type="integer", label="主题数", min_value=1),
            SettingFieldSpec(path=("topic_model", "passes"), field_type="integer", label="训练轮数", min_value=1),
            SettingFieldSpec(path=("topic_model", "iterations"), field_type="integer", label="迭代次数", min_value=1),
            SettingFieldSpec(
                path=("topic_model", "num_topics_min"), field_type="integer", label="主题数下限", min_value=1
            ),
            SettingFieldSpec(
                path=("topic_model", "num_topics_max"), field_type="integer", label="主题数上限", min_value=1
            ),
            SettingFieldSpec(
                path=("topic_model", "num_topics_scaling_divisor"),
                field_type="integer",
                label="主题数缩放除数",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("topic_model", "lda", "alpha"),
                field_type="string",
                label="LDA alpha",
                description='"auto" 或数值',
            ),
            SettingFieldSpec(
                path=("topic_model", "lda", "eta"), field_type="string", label="LDA eta", description='"auto" 或数值'
            ),
            SettingFieldSpec(
                path=("topic_model", "lda", "random_state"), field_type="integer", label="LDA 随机种子"
            ),
            SettingFieldSpec(
                path=("topic_model", "lda", "lda_batch_size"), field_type="integer", label="LDA 批大小", min_value=1
            ),
            SettingFieldSpec(
                path=("topic_model", "lda", "minimum_probability"),
                field_type="number",
                label="最小主题概率",
                min_value=0,
                max_value=1,
                step=0.01,
            ),
            SettingFieldSpec(
                path=("topic_model", "lda", "no_below"), field_type="integer", label="词频下限", min_value=1
            ),
            SettingFieldSpec(
                path=("topic_model", "lda", "no_above"),
                field_type="number",
                label="词频上限比例",
                min_value=0,
                max_value=1,
                step=0.05,
            ),
            SettingFieldSpec(
                path=("topic_model", "topic_shift", "window_size"),
                field_type="integer",
                label="主题变化窗口大小",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("topic_model", "topic_shift", "min_tokens_per_window"),
                field_type="integer",
                label="窗口最小 token 数",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("topic_model", "topic_shift", "score_threshold"),
                field_type="number",
                label="主题变化分数阈值",
                min_value=0,
                max_value=1,
                step=0.05,
            ),
            SettingFieldSpec(
                path=("topic_model", "topic_shift", "max_candidates"),
                field_type="integer",
                label="主题变化候选上限",
                min_value=1,
            ),
            # ---- metrics ----
            SettingFieldSpec(
                path=("metrics", "mtld_threshold"), field_type="number", label="MTLD 阈值", min_value=0, max_value=1
            ),
            SettingFieldSpec(
                path=("metrics", "middle_collapse_min_chunks"),
                field_type="integer",
                label="中部塌缩块数阈值",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("metrics", "small_sample_min_chapters"),
                field_type="integer",
                label="小样本最少章数",
                min_value=1,
                description="低于该章数时比率/结构指标返回 null，不输出伪精确值",
            ),
            SettingFieldSpec(
                path=("metrics", "function_word_min_chars"),
                field_type="integer",
                label="虚字指纹最少字符数",
                min_value=1,
            ),
            SettingFieldSpec(
                path=("metrics", "character_max_iter"), field_type="integer", label="角色指标最大迭代", min_value=1
            ),
            # ---- linguistic.ltp ----
            SettingFieldSpec(path=("linguistic", "ltp", "enabled"), field_type="boolean", label="启用 LTP"),
            SettingFieldSpec(
                path=("linguistic", "ltp", "max_length"), field_type="integer", label="LTP 最大长度", min_value=1
            ),
            SettingFieldSpec(
                path=("linguistic", "ltp", "dep_root_index"), field_type="integer", label="依存根索引", min_value=0
            ),
            # ---- linguistic.word2vec ----
            SettingFieldSpec(path=("linguistic", "word2vec", "enabled"), field_type="boolean", label="启用 Word2Vec"),
            SettingFieldSpec(
                path=("linguistic", "word2vec", "model_dir"),
                field_type="string",
                label="预训练共享模型目录",
                description="目录内应恰有一个 .kv 文件（由 convert_word2vec_pretrained.py 生成）",
            ),
            SettingFieldSpec(
                path=("linguistic", "word2vec", "window"), field_type="integer", label="窗口大小", min_value=1
            ),
            SettingFieldSpec(
                path=("linguistic", "word2vec", "min_count"), field_type="integer", label="最小词频", min_value=1
            ),
            SettingFieldSpec(
                path=("linguistic", "word2vec", "epochs"), field_type="integer", label="训练轮数", min_value=1
            ),
        ]
    )
)

__all__ = [
    "SETTING_SECTIONS",
    "SETTING_FIELDS",
    "SETTING_FIELD_TYPES",
    "MODEL_ENV_KEYS",
    "SettingSectionSpec",
    "SettingFieldSpec",
]
