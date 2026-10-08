"""响应装配测试的显式领域查询夹具，不依赖已经删除的生产仓储方法"""

from __future__ import annotations

from inspect import signature
from types import SimpleNamespace
from unittest.mock import patch

from src.api.services.results_queries.chapters import _fetch_chapter_annotations as _chapter_response
from src.api.services.results_queries.characters import _fetch_characters as _character_response
from src.api.services.results_queries.foreshadowing_trees import _fetch_foreshadowing_trees as _tree_response


def _fixture_arguments(function, args, kwargs):
    bound = signature(function).bind(*args, **kwargs)
    repo = bound.arguments["annotation_repo"]
    bound.arguments["annotation_repo"] = SimpleNamespace(session=getattr(repo, "session", object()))
    return repo, bound


def _fetch_chapter_annotations(*args, **kwargs):
    repo, bound = _fixture_arguments(_chapter_response, args, kwargs)
    with (
        patch(
            "src.api.services.results_queries.chapters.fetch_chapter_annotations_full",
            side_effect=lambda _session, run: repo.fetch_chapter_annotations_full(run),
        ),
        patch(
            "src.api.services.results_queries.chapters.fetch_chapter_characters_full",
            side_effect=lambda _session, run: repo.fetch_chapter_characters_full(run),
        ),
        patch(
            "src.api.services.results_queries.chapters.fetch_chapter_dialogues_full",
            side_effect=lambda _session, run: repo.fetch_chapter_dialogues_full(run),
        ),
    ):
        return _chapter_response(*bound.args, **bound.kwargs)


def _fetch_characters(*args, **kwargs):
    repo, bound = _fixture_arguments(_character_response, args, kwargs)
    with patch(
        "src.api.services.results_queries.characters.fetch_chapter_characters_full",
        side_effect=lambda _session, run: repo.fetch_chapter_characters_full(run),
    ):
        return _character_response(*bound.args, **bound.kwargs)


def _fetch_foreshadowing_trees(*args, **kwargs):
    repo, bound = _fixture_arguments(_tree_response, args, kwargs)
    with patch(
        "src.api.services.results_queries.foreshadowing_trees.fetch_foreshadowing_trees",
        side_effect=lambda _session, run: repo.fetch_foreshadowing_trees(run),
    ):
        return _tree_response(*bound.args, **bound.kwargs)
