import re
from typing import Match, Optional

filepath = r'e:\projects\python-projects\novel quantitative analysis\data\lexicons\semantic_category.txt'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

categories: dict[str, list[str]] = {}
current_cat: Optional[str] = None
current_words: list[str] = []

for line in content.split('\n'):
    if line.startswith('# ====='):
        if current_cat and current_words:
            categories[current_cat] = current_words
        match: Optional[Match[str]] = re.search(r'\d+\.\s*(.+?)类', line)
        if match:
            current_cat = match.group(1)
        current_words = []
    elif line.strip() and not line.startswith('#'):
        current_words.append(line.strip())

if current_cat and current_words:
    categories[current_cat] = current_words

result_lines: list[str] = []
lines = content.split('\n')
current_cat = None
seen_in_cat: set[str] = set()

for line in lines:
    if line.startswith('# ====='):
        if current_cat:
            seen_in_cat = set()
        cat_match = re.search(r'\d+\.\s*(.+?)类', line)
        current_cat = cat_match.group(1) if cat_match else None
        result_lines.append(line)
    elif line.strip() and not line.startswith('#'):
        word = line.strip()
        if word not in seen_in_cat:
            seen_in_cat.add(word)
            result_lines.append(line)
    else:
        result_lines.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(result_lines))

print("类内去重完成")

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

categories = {}
current_cat = None
current_words = []

for line in content.split('\n'):
    if line.startswith('# ====='):
        if current_cat and current_words:
            categories[current_cat] = current_words
        match = re.search(r'\d+\.\s*(.+?)类', line)
        if match:
            current_cat = match.group(1)
        current_words = []
    elif line.strip() and not line.startswith('#'):
        current_words.append(line.strip())

if current_cat and current_words:
    categories[current_cat] = current_words

print("\n各类别词条数量:")
for cat, words in categories.items():
    print(f"  {cat}: {len(words)}条")

print("\n类内重复检测:")
for cat, words in categories.items():
    seen: set[str] = set()
    dups: list[str] = []
    for w in words:
        if w in seen:
            dups.append(w)
        else:
            seen.add(w)
    if dups:
        print(f"  {cat}: {dups}")
