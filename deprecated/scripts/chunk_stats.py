import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.chunking.chunker import chunk_text
from src.ingest.reader import ingest_path
from src.lexicons.loader import update_lexicons_from_texts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-update-lexicons", action="store_true")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    novel_dir = repo_root / "data" / "novel"
    docs = ingest_path(novel_dir)
    text = docs[0].text
    chunks = chunk_text(text, max_chars=2000, overlap=200, split_by_chapter=True)
    if args.auto_update_lexicons:
        update_lexicons_from_texts([chunk.text for chunk in chunks], repo_root / "data" / "lexicons")
    lengths = [len(chunk.text) for chunk in chunks]
    avg_len = sum(lengths) / len(lengths)
    over_2500 = sum(1 for length in lengths if length > 2500)
    print(
        "chars="
        + str(len(text))
        + " chunks="
        + str(len(chunks))
        + " avg_len="
        + str(round(avg_len, 2))
        + " min_len="
        + str(min(lengths))
        + " max_len="
        + str(max(lengths))
        + " over_2500="
        + str(over_2500)
    )


if __name__ == "__main__":
    main()
