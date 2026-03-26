import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.lexicons.loader import load_all_lexicons, match_terms


def main() -> None:
    text = "赵云飞在紫霄城外拔剑一斩，杀意爆裂，刺鼻的血腥气混着幽香。"
    lexicons = load_all_lexicons()
    result = {
        name: sorted(match_terms(text, terms)) for name, terms in lexicons.items()
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
