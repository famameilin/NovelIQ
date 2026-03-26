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

print("=" * 60)
print("各类别词条数量统计")
print("=" * 60)
for cat, words in categories.items():
    print(f"{cat}: {len(words)}条")

print("\n" + "=" * 60)
print("各类别内部重复检测")
print("=" * 60)
for cat, words in categories.items():
    seen: set[str] = set()
    dups: list[str] = []
    for w in words:
        if w in seen:
            dups.append(w)
        else:
            seen.add(w)
    if dups:
        print(f"\n{cat}类重复词条({len(dups)}个):")
        print(f"  {dups[:20]}{'...' if len(dups) > 20 else ''}")

print("\n" + "=" * 60)
print("类别间交叉检测")
print("=" * 60)
cat_names = list(categories.keys())
for i in range(len(cat_names)):
    for j in range(i + 1, len(cat_names)):
        set1 = set(categories[cat_names[i]])
        set2 = set(categories[cat_names[j]])
        inter = set1 & set2
        if inter:
            print(f"\n{cat_names[i]} ∩ {cat_names[j]}: {len(inter)}个")
            print(f"  {list(inter)[:15]}{'...' if len(inter) > 15 else ''}")

print("\n" + "=" * 60)
print("第10类色彩形容词异常检测")
print("=" * 60)
color_words = categories.get('色彩形容', [])
non_color: list[str] = []
color_bases = ['红', '橙', '黄', '绿', '青', '蓝', '紫', '白', '黑', '灰', '金', '银', 
               '朱', '赤', '丹', '彤', '绯', '绛', '赭', '褐', '棕', '驼', '米', '杏', '乳', '雪', '霜']
for w in color_words:
    is_color = False
    for base in color_bases:
        if base in w or w in ['红', '橙', '黄', '绿', '青', '蓝', '紫', '白', '黑', '灰', '金', '银']:
            is_color = True
            break
    if not is_color and len(w) <= 2:
        non_color.append(w)

print(f"疑似非色彩词条({len(non_color)}个):")
print(f"  {non_color}")

print("\n" + "=" * 60)
print("第8类度量形容词异常检测")
print("=" * 60)
measure_words = categories.get('度量形容', [])
verbs_in_measure: list[str] = []
verb_indicators = ['跑', '走', '飞', '游', '爬', '跳', '打', '杀', '砍', '煮', '炒', '炸', '烤', '烧', '炖', '蒸', '熬', '煎', '烙', '烘', '晒', '晾', '冻', '冰', '化', '融', '解', '凝', '固']
for w in measure_words:
    for v in verb_indicators:
        if v == w:
            verbs_in_measure.append(w)
            break

print(f"疑似动词词条({len(verbs_in_measure)}个):")
print(f"  {verbs_in_measure[:30]}")
