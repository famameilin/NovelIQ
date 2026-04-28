"""
本模块包含API和路径相关的配置数据类
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def load_prompt_from_file(prompt_name: str, config_dir: Path | None = None) -> str:
    """
    从文件加载 prompt

    说明: 从 config/prompts/ 目录加载 prompt 文件

    Args:
        prompt_name: prompt 文件名（不含扩展名）
        config_dir: 配置目录路径，默认为项目根目录下的 config

    Returns:
        prompt 内容，如果文件不存在则返回空字符串
    """
    if config_dir is None:
        config_dir = Path(__file__).parent.parent.parent.parent / "config"
    prompt_file = config_dir / "prompts" / f"{prompt_name}.txt"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8").strip()
    return ""


def parse_prompt_sections(content: str) -> dict[str, str]:
    """
    解析包含多个分段的 prompt 文件

    说明: 解析使用 ===SECTION_NAME=== 标记的分段 prompt

    Args:
        content: prompt 文件内容

    Returns:
        分段名称到内容的映射
    """
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_content: list[str] = []

    for line in content.split("\n"):
        if line.startswith("===") and line.endswith("==="):
            if current_section is not None:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line.strip("=")
            current_content = []
        else:
            current_content.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def parse_few_shot_examples(content: str) -> list[dict[str, str]]:
    """
    解析 Few-shot 示例

    说明: 解析使用 ---EXAMPLE_N_USER--- 和 ---EXAMPLE_N_ASSISTANT--- 标记的示例

    Args:
        content: FEW_SHOT 分段的内容

    Returns:
        示例列表，每个示例包含 user 和 assistant 两个键
    """
    examples: list[dict[str, str]] = []
    current_user: str | None = None
    current_assistant: str | None = None
    current_content: list[str] = []
    current_section: str | None = None

    for line in content.split("\n"):
        if line.startswith("---EXAMPLE_") and "_USER---" in line:
            if current_user is not None and current_assistant is not None:
                examples.append({"user": current_user, "assistant": current_assistant})
            current_user = None
            current_assistant = None
            current_section = "user"
            current_content = []
        elif line.startswith("---EXAMPLE_") and "_ASSISTANT---" in line:
            if current_section == "user":
                current_user = "\n".join(current_content).strip()
            current_section = "assistant"
            current_content = []
        elif line.startswith("===") and line.endswith("==="):
            if current_section == "assistant":
                current_assistant = "\n".join(current_content).strip()
                if current_user is not None and current_assistant is not None:
                    examples.append({"user": current_user, "assistant": current_assistant})
            break
        else:
            current_content.append(line)

    if current_section == "assistant":
        current_assistant = "\n".join(current_content).strip()
        if current_user is not None and current_assistant is not None:
            examples.append({"user": current_user, "assistant": current_assistant})

    return examples


@dataclass
class Phase1Prompts:

    system: str = ""
    user_template: str = ""
    few_shot: list[dict[str, str]] = field(default_factory=list)
    format: str = ""


@dataclass
class Phase2Prompts:

    system: str = ""
    user_template: str = ""
    examples: str = ""


@dataclass
class Phase3Prompts:

    system: str = ""
    user_template: str = ""
    dialogue_batch_size: int = 5


@dataclass
class Phase4Prompts:

    system: str = ""
    user_template: str = ""


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
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = field(default_factory=lambda: ["*"])
    cors_allow_headers: list[str] = field(default_factory=lambda: ["*"])
    novel_name_max_length: int = 50
    query_limit: int = 50


@dataclass
class PromptSettings:
    """
    Prompt 配置
    """

    phase1: Phase1Prompts = field(default_factory=Phase1Prompts)
    phase2: Phase2Prompts = field(default_factory=Phase2Prompts)
    phase3: Phase3Prompts = field(default_factory=Phase3Prompts)
    phase4: Phase4Prompts = field(default_factory=Phase4Prompts)
    disambiguate: str = ""
    reselect_canonical: str = ""
    anonymous_disambig: str = ""
    diagnose: str = ""


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


def _load_phase1_prompts() -> Phase1Prompts:
    """
    加载 Phase1 prompt
    """
    content = load_prompt_from_file("phase1")
    if not content:
        return Phase1Prompts()

    sections = parse_prompt_sections(content)
    few_shot: list[dict[str, str]] = []
    if "FEW_SHOT" in sections:
        few_shot = parse_few_shot_examples(sections["FEW_SHOT"])

    return Phase1Prompts(
        system=sections.get("SYSTEM", ""),
        user_template=sections.get("USER_TEMPLATE", ""),
        few_shot=few_shot,
        format=sections.get("FORMAT", ""),
    )


def _load_phase2_prompts() -> Phase2Prompts:
    """
    加载 Phase2 prompt
    """
    content = load_prompt_from_file("phase2")
    if not content:
        return Phase2Prompts()

    sections = parse_prompt_sections(content)
    return Phase2Prompts(
        system=sections.get("SYSTEM", ""),
        user_template=sections.get("USER_TEMPLATE", ""),
        examples=sections.get("EXAMPLES", ""),
    )


def _load_phase3_prompts() -> Phase3Prompts:
    """
    加载 Phase3 prompt
    """
    content = load_prompt_from_file("phase3")
    if not content:
        return Phase3Prompts()

    sections = parse_prompt_sections(content)
    return Phase3Prompts(
        system=sections.get("SYSTEM", ""),
        user_template=sections.get("USER_TEMPLATE", ""),
    )


def _load_phase4_prompts() -> Phase4Prompts:
    """
    加载 Phase4 prompt
    """
    from loguru import logger

    content = load_prompt_from_file("phase4")
    if not content:
        logger.warning("Phase4 prompt file not found or empty")
        return Phase4Prompts()

    sections = parse_prompt_sections(content)
    prompts = Phase4Prompts(
        system=sections.get("SYSTEM", ""),
        user_template=sections.get("USER_TEMPLATE", ""),
    )

    if not prompts.system:
        logger.warning("Phase4 prompt: SYSTEM section is empty")
    if not prompts.user_template:
        logger.warning("Phase4 prompt: USER_TEMPLATE section is empty")

    return prompts


def _parse_prompt_settings(data: dict[str, Any] | None) -> PromptSettings:
    """
    解析 Prompt 配置
    """
    return PromptSettings(
        phase1=_load_phase1_prompts(),
        phase2=_load_phase2_prompts(),
        phase3=_load_phase3_prompts(),
        phase4=_load_phase4_prompts(),
        disambiguate=load_prompt_from_file("disambiguate"),
        reselect_canonical=load_prompt_from_file("reselect_canonical"),
        anonymous_disambig=load_prompt_from_file("anonymous_disambig"),
        diagnose=load_prompt_from_file("diagnose"),
    )
