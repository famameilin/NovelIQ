from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any


class CacheStore:
    def has(self, key: str) -> bool:
        raise NotImplementedError

    def get(self, key: str) -> Any:
        raise NotImplementedError

    def set(self, key: str, value: Any) -> None:
        raise NotImplementedError


class MemoryCache(CacheStore):
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def has(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str) -> Any:
        return self._data[key]

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value


class FileCache(CacheStore):
    def __init__(self, path: Path) -> None:
        self._path = path
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def has(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str) -> Any:
        return self._data[key]

    def set(self, key: str, value: Any) -> None:
        serializable = value.to_dict() if hasattr(value, "to_dict") else value
        self._data[key] = serializable
        self._path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")


@dataclass(frozen=True)
class PipelineContext:
    payload: dict[str, Any]
    cache_key_base: str


@dataclass(frozen=True)
class Stage:
    name: str
    handler: Callable[[dict[str, Any], dict[str, Any]], Any]
    dependencies: list[str] = field(default_factory=list)


def compute_cache_key(cache_key_base: str, stage_name: str) -> str:
    digest = sha256(f"{cache_key_base}:{stage_name}".encode()).hexdigest()
    return digest


def run_pipeline(
    stages: Iterable[Stage],
    context: PipelineContext,
    cache: CacheStore | None = None,
    force: bool = False,
    rerun_stages: Iterable[str] | None = None,
) -> dict[str, Any]:
    stage_map = {stage.name: stage for stage in stages}
    rerun = set(rerun_stages or [])
    outputs: dict[str, Any] = {}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_name: str) -> None:
        if stage_name in visited:
            return
        if stage_name in visiting:
            raise ValueError(f"cycle detected at {stage_name}")
        if stage_name not in stage_map:
            raise KeyError(f"stage not found: {stage_name}")
        visiting.add(stage_name)
        stage = stage_map[stage_name]
        for dep in stage.dependencies:
            visit(dep)
        cache_key = compute_cache_key(context.cache_key_base, stage_name)
        if cache is not None and not force and stage_name not in rerun:
            if cache.has(cache_key):
                outputs[stage_name] = cache.get(cache_key)
                visiting.remove(stage_name)
                visited.add(stage_name)
                return
        result = stage.handler(context.payload, outputs)
        outputs[stage_name] = result
        if cache is not None:
            cache.set(cache_key, result)
        visiting.remove(stage_name)
        visited.add(stage_name)

    for stage in stages:
        visit(stage.name)
    return outputs
