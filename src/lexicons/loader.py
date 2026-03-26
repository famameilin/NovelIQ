from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def _default_lexicon_dir() -> Path:
    return Path("data/lexicons")


def _clean_line(line: str) -> str:
    cleaned = line.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("#"):
        return ""
    return cleaned


def load_lexicon(name: str, base_dir: Path | None = None) -> list[str]:
    lexicon_dir = base_dir or _default_lexicon_dir()
    path = lexicon_dir / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"lexicon not found: {path}")
    items: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        item = _clean_line(line)
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            items.append(item)
    return items


def load_all_lexicons(
    base_dir: Path | None = None,
    auto_update_texts: Iterable[str] | None = None,
    apply_updates: bool = True,
) -> dict[str, list[str]]:
    lexicon_dir = base_dir or _default_lexicon_dir()
    if auto_update_texts is not None:
        from src.lexicons.suggest import update_lexicons_from_texts

        update_lexicons_from_texts(auto_update_texts, lexicon_dir, apply=apply_updates)
    lexicons: dict[str, list[str]] = {}
    for path in sorted(lexicon_dir.glob("*.txt")):
        lexicons[path.stem] = load_lexicon(path.stem, lexicon_dir)
    return lexicons


def update_lexicons_from_texts(
    texts: Iterable[str],
    base_dir: Path | None = None,
    apply_updates: bool = True,
) -> dict[str, list[str]]:
    lexicon_dir = base_dir or _default_lexicon_dir()
    from src.lexicons.suggest import update_lexicons_from_texts as _update

    return _update(texts, lexicon_dir, apply=apply_updates)


def match_terms(text: str, terms: Iterable[str]) -> set[str]:
    hits: set[str] = set()
    for term in terms:
        if term and term in text:
            hits.add(term)
    return hits
