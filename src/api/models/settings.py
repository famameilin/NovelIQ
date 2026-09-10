"""2026-09-10 设置模块 API 契约（/api/settings）

设置页三条通道：
- 字段注册表 + 生效值视图（schema 驱动表单）
- 用户设置保存（settings.json 稀疏覆盖，保存即原地热生效）
- 模型凭据（.env 白名单键编辑器，key 只存 .env 一处）
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SettingFieldType = Literal["number", "integer", "boolean", "enum", "string"]


class SettingSectionSpecResponse(BaseModel):
    """设置分区元数据（前端渲染为一个分区卡片）"""

    id: str = Field(description="分区 id（settings.json 顶层 section 名）")
    title: str = Field(description="分区标题")
    description: str = Field(default="", description="分区说明")
    order: int = Field(default=0, description="展示顺序")


class SettingFieldSpecResponse(BaseModel):
    """单个可调参数声明（path 是 settings.json 中的结构化路径，dict 键可含点不做字符串拼接约定）"""

    path: list[str] = Field(description="结构化路径，如 [\"models\", \"annotation\", \"temperature\"]")
    field_type: SettingFieldType = Field(description="字段类型，驱动前端控件选择")
    label: str = Field(description="展示名")
    description: str = Field(default="", description="字段说明")
    min_value: float | None = Field(default=None, description="数值下界")
    max_value: float | None = Field(default=None, description="数值上界")
    step: float | None = Field(default=None, description="数值步进")
    enum_values: list[str] = Field(default_factory=list, description="enum 类型的可选值")
    nullable: bool = Field(default=False, description="是否允许 null（如 timeout_s 未设置）")
    editable: bool = Field(default=True, description="是否可在运行时修改（False 仅展示说明）")


class SettingsSchemaResponse(BaseModel):
    """字段注册表（默认值不在响应中声明，经 values/defaults 视图合并输出）"""

    sections: list[SettingSectionSpecResponse]
    fields: list[SettingFieldSpecResponse]


class SettingsViewResponse(BaseModel):
    """设置视图：生效值 + 默认值 + 逐字段来源

    values 中 api_key 一律打码（"••••" 前缀 + 尾 4 位），明文只在 .env。
    sources 键为 "/".join(path)，值 "default"（代码默认）或 "file"（settings.json 覆盖）。
    """

    values: dict[str, Any] = Field(description="当前生效值（默认值 ← settings.json ← env 凭据 叠加结果）")
    defaults: dict[str, Any] = Field(description="代码内 dataclass 默认值")
    sources: dict[str, str] = Field(description="逐字段来源")


class UpdateSettingsRequest(BaseModel):
    """保存用户设置：values 与当前文件内容深合并后整体校验写回（稀疏化保存）"""

    values: dict[str, Any] = Field(description="要保存的设置（支持部分提交，未提及的键保留文件现值）")


class TaskEnvPatchRequest(BaseModel):
    """单任务组凭据补丁：api_key None=不改，""=整组清空，非空=设置"""

    base_url: str | None = Field(default=None, description="服务地址；None=不修改")
    model: str | None = Field(default=None, description="模型 ID；None=不修改")
    api_key: str | None = Field(default=None, description='凭据；None=不修改，""=整组清空')


class ModelEnvUpdateRequest(BaseModel):
    """模型凭据更新（.env 白名单键写入 + os.environ 同步 + 单例原地生效）"""

    model: TaskEnvPatchRequest | None = Field(default=None, description="文本模型（annotation/diagnosis 共用）")
    embedding_model: TaskEnvPatchRequest | None = Field(default=None, description="嵌入模型（llama-server）")
    ltp_model_dir: str | None = Field(default=None, description="LTP 模型目录；None=不修改，非空需为存在的目录")


class ModelProviderTestRequest(BaseModel):
    """测试连接请求：字段缺省时使用当前生效配置"""

    base_url: str | None = Field(default=None, description="覆盖当前 base_url")
    api_key: str | None = Field(default=None, description="覆盖当前 api_key（明文，不落盘）")


class ModelProviderTestResponse(BaseModel):
    """测试连接结果：ok=false 时 error 携带可读原因"""

    ok: bool
    latency_ms: float | None = Field(default=None, description="请求耗时（毫秒）")
    model_ids: list[str] = Field(default_factory=list, description="服务端可用模型 ID（最多 20 条）")
    error: str | None = Field(default=None, description="失败原因")
