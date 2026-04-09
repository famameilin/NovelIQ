"""
从情感词典提取词条生成jieba用户词典

创建时间: 2026-04-06
创建者: GLM-5
任务: 从情感词典提取2字及以上词条，生成jieba用户词典
说明: 读取positive.txt和negative.txt，提取2字及以上词条，去重后按长度排序输出
"""

from pathlib import Path


def extract_words_from_lexicon(file_path: str) -> set[str]:
    """
    从情感词典文件中提取词条

    参数:
        file_path: 词典文件路径

    返回:
        词条集合
    """
    words: set[str] = set()

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")
            if len(parts) >= 1:
                word = parts[0].strip()
                if len(word) >= 2:
                    words.add(word)

    return words


def generate_jieba_dict(
    positive_path: str, negative_path: str, output_path: str
) -> tuple[int, str]:
    """
    生成jieba用户词典

    参数:
        positive_path: 正面情感词典路径
        negative_path: 负面情感词典路径
        output_path: 输出文件路径

    返回:
        (词条数量, 输出文件路径)
    """
    positive_words = extract_words_from_lexicon(positive_path)
    negative_words = extract_words_from_lexicon(negative_path)

    all_words = positive_words | negative_words

    sorted_words = sorted(all_words, key=lambda x: len(x), reverse=True)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# jieba用户词典 - 情感词条\n")
        f.write(f"# 来源: positive.txt, negative.txt\n")
        f.write(f"# 词条数量: {len(sorted_words)}个\n")
        f.write(f"# 生成时间: 2026-04-06\n")
        f.write(f"# 说明: 提取自情感词典的2字及以上词条，按长度降序排列\n")
        f.write("# 格式: 词条（jieba默认格式，每行一个词条）\n")
        f.write("\n")

        for word in sorted_words:
            f.write(f"{word}\n")

    return len(sorted_words), output_path


if __name__ == "__main__":
    base_path = Path(__file__).parent.parent / "data" / "lexicons"

    positive_path = base_path / "positive.txt"
    negative_path = base_path / "negative.txt"
    output_path = base_path / "jieba_user_dict.txt"

    count, path = generate_jieba_dict(
        str(positive_path), str(negative_path), str(output_path)
    )

    print(f"生成的词条数量: {count}个")
    print(f"输出文件路径: {path}")
