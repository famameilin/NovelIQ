"""检查词表覆盖情况"""
from src.lexicons.registry import LexiconRegistry

reg = LexiconRegistry()
reg.load()

print("=== 基础词表 ===")
print(f"positive.txt: {len(reg.get('emotion.positive'))} 词")
print(f"negative.txt: {len(reg.get('emotion.negative'))} 词")
print(f"combat.txt: {len(reg.get('tension.action_terms'))} 词")

print("\n=== 领域词表 ===")
domains = [
    "xianxia_positive",
    "xianxia_negative",
    "urban_positive",
    "urban_negative",
    "power_struggle",
    "shuwen_pattern",
]
for d in domains:
    terms = reg.get(f"domain.{d}")
    print(f"{d}: {len(terms)} 词")

print("\n=== 领域词表内容示例 ===")
for d in domains[:3]:
    terms = reg.get(f"domain.{d}")
    sample = list(terms)[:5]
    print(f"{d}: {sample}")
