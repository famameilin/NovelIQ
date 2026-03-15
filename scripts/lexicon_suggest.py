from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.chunking.chunker import chunk_text
from src.ingest.reader import ingest_path
from src.lexicons.suggest import apply_updates, expand_lexicons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    novel_dir = repo_root / "data" / "novel"
    docs = ingest_path(novel_dir)
    chunks = chunk_text(docs[0].text, max_chars=2000, overlap=200, split_by_chapter=True)
    texts = [chunk.text for chunk in chunks]
    lexicon_dir = repo_root / "data" / "lexicons"
    additions = expand_lexicons(texts, lexicon_dir)
    for name, terms in additions.items():
        if terms:
            print(name, len(terms))
            print(" ".join(terms))
    if args.apply:
        apply_updates(additions, lexicon_dir)


if __name__ == "__main__":
    main()
