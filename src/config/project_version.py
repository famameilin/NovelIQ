"项目发布版本的唯一读取入口"

import tomllib
from functools import cache
from pathlib import Path


@cache
def project_version() -> str:
    "读取项目清单中的发布版本，不依赖当前工作目录"
    manifest = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with manifest.open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])
