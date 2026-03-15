"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 settings.py 拆分API相关配置类

本模块包含API和路径相关的配置数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List


@dataclass
class PathSettings:
    """路径配置"""

    upload_dir: Path = field(default_factory=lambda: Path("data/uploads"))
    results_dir: Path = field(default_factory=lambda: Path("outputs"))
    log_dir: Path = field(default_factory=lambda: Path("logs"))
    lexicons_dir: Path = field(default_factory=lambda: Path("data/lexicons"))

    def __post_init__(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class APISettings:
    """API服务配置"""

    title: str = "小说量化分析 API"
    version: str = "0.1.0"
    description: str = "小说文本量化分析服务的 RESTful API"
    docs_url: str = "/api/docs"
    redoc_url: str = "/api/redoc"
    openapi_url: str = "/api/openapi.json"
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = field(default_factory=lambda: ["*"])
    cors_allow_headers: List[str] = field(default_factory=lambda: ["*"])
    novel_name_max_length: int = 50
    query_limit: int = 50


@dataclass
class PromptSettings:
    """
    Prompt配置

    修改时间: 2026-03-14
    修改者: TraeAI
    修改内容: 添加双次调用标注相关prompt配置
    - local_annotation_system_v2: 第一次调用（基础标注）的System Prompt
    - local_annotation_format_v2: 第一次调用的输出格式
    - local_annotation_few_shot_v2: 第一次调用的Few-shot示例
    - local_annotation_user_template: 第一次调用的User Prompt模板
    - foreshadowing_system: 第二次调用（伏笔分析）的System Prompt
    - foreshadowing_user_template: 第二次调用的User Prompt模板
    - foreshadowing_examples: 第二次调用的Few-shot示例
    """

    local_annotation_system: str = ""
    local_annotation_format: str = ""
    local_annotation_few_shot: list[dict[str, str]] = field(default_factory=list)
    local_disambiguate_system: str = ""
    local_anonymous_disambig_system: str = ""
    cloud_diagnose_system: str = ""
    local_annotation_system_v2: str = ""
    local_annotation_format_v2: str = ""
    local_annotation_few_shot_v2: list[dict[str, str]] = field(default_factory=list)
    local_annotation_user_template: str = ""
    foreshadowing_system: str = ""
    foreshadowing_user_template: str = ""
    foreshadowing_examples: str = ""


def _parse_path_settings(data: dict[str, Any] | None) -> PathSettings:
    """解析路径配置"""
    if not data:
        return PathSettings()
    return PathSettings(
        upload_dir=Path(data.get("upload_dir", "data/uploads")),
        results_dir=Path(data.get("results_dir", "outputs")),
        log_dir=Path(data.get("log_dir", "logs")),
        lexicons_dir=Path(data.get("lexicons_dir", "data/lexicons")),
    )


def _parse_api_settings(data: dict[str, Any] | None) -> APISettings:
    """解析API配置"""
    if not data:
        return APISettings()
    return APISettings(
        title=data.get("title", "小说量化分析 API"),
        version=data.get("version", "0.1.0"),
        description=data.get("description", ""),
        docs_url=data.get("docs_url", "/api/docs"),
        redoc_url=data.get("redoc_url", "/api/redoc"),
        openapi_url=data.get("openapi_url", "/api/openapi.json"),
        cors_origins=data.get("cors_origins", ["*"]),
        cors_allow_credentials=data.get("cors_allow_credentials", True),
        cors_allow_methods=data.get("cors_allow_methods", ["*"]),
        cors_allow_headers=data.get("cors_allow_headers", ["*"]),
        novel_name_max_length=data.get("novel_name_max_length", 50),
        query_limit=data.get("query_limit", 50),
    )


def _parse_prompt_settings(data: dict[str, Any] | None) -> PromptSettings:
    """
    解析Prompt配置

    修改时间: 2026-03-14
    修改者: TraeAI
    修改内容: 添加双次调用标注相关prompt配置解析
    """
    if not data:
        return PromptSettings()
    return PromptSettings(
        local_annotation_system=data.get("local_annotation_system", ""),
        local_annotation_format=data.get("local_annotation_format", ""),
        local_annotation_few_shot=data.get("local_annotation_few_shot", []),
        local_disambiguate_system=data.get("local_disambiguate_system", ""),
        local_anonymous_disambig_system=data.get("local_anonymous_disambig_system", ""),
        cloud_diagnose_system=data.get("cloud_diagnose_system", ""),
        local_annotation_system_v2=data.get("local_annotation_system_v2", ""),
        local_annotation_format_v2=data.get("local_annotation_format_v2", ""),
        local_annotation_few_shot_v2=data.get("local_annotation_few_shot_v2", []),
        local_annotation_user_template=data.get("local_annotation_user_template", ""),
        foreshadowing_system=data.get("foreshadowing_system", ""),
        foreshadowing_user_template=data.get("foreshadowing_user_template", ""),
        foreshadowing_examples=data.get("foreshadowing_examples", ""),
    )
