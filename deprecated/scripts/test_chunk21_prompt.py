"""
测试 Chunk 21 标注 Prompt（完整版）

创建时间: 2026-03-12
创建者: TraeAI
任务: 测试完整的 Prompt 格式
"""
import json
import re
from openai import OpenAI

# 读取完整的 prompt 文件
with open('logs/chunk21_prompt.txt', 'r', encoding='utf-8') as f:
    content = f.read()

# 解析 prompt
sections = content.split('================================================================================')

system_prompt = ""
few_shot_examples = []
user_message = ""
format_requirements = ""

for i, section in enumerate(sections):
    section = section.strip()
    if not section:
        continue
    
    # System Prompt 在【System Prompt】标签后的下一个 section
    if '【System Prompt】' in section:
        # 找到下一个非空 section
        for j in range(i + 1, len(sections)):
            next_section = sections[j].strip()
            if next_section and '【' not in next_section:
                system_prompt = next_section
                break
    
    elif '【Few-shot Examples】' in section:
        # 找到 few-shot examples 的内容
        for j in range(i + 1, len(sections)):
            next_section = sections[j].strip()
            if next_section and '【User Message】' not in next_section:
                examples_text = next_section
                # 使用正则表达式匹配每个 example
                pattern = r'Example \d+[^:]*:\s*-+\s*User:\s*(.*?)\s*Assistant:\s*(\{[\s\S]*?\})\s*(?=Example|\Z)'
                matches = re.findall(pattern, examples_text, re.DOTALL)
                for user_text, assistant_text in matches:
                    few_shot_examples.append({
                        "user": user_text.strip(),
                        "assistant": assistant_text.strip()
                    })
                break
    
    elif '【User Message】' in section:
        # 找到 user message 的内容
        for j in range(i + 1, len(sections)):
            next_section = sections[j].strip()
            if next_section and '【格式要求】' not in next_section:
                user_message = next_section
                break
    
    elif '【格式要求】' in section:
        # 找到格式要求的内容
        for j in range(i + 1, len(sections)):
            next_section = sections[j].strip()
            if next_section:
                format_requirements = next_section
                break

print("="*80)
print("Prompt 解析结果")
print("="*80)
print(f"System prompt 长度: {len(system_prompt)}")
print(f"System prompt 内容: {system_prompt[:100]}...")
print(f"Few-shot examples 数量: {len(few_shot_examples)}")
print(f"User message 长度: {len(user_message)}")
print(f"Format requirements 长度: {len(format_requirements)}")

if few_shot_examples:
    print(f"\n第一个 example user 长度: {len(few_shot_examples[0]['user'])}")
    print(f"第一个 example user 内容: {few_shot_examples[0]['user'][:100]}...")

# 构建消息
messages = [{"role": "system", "content": system_prompt}]

for example in few_shot_examples:
    messages.append({"role": "user", "content": example["user"]})
    messages.append({"role": "assistant", "content": example["assistant"]})

# 添加当前用户消息
full_user_message = user_message + "\n\n" + format_requirements
messages.append({"role": "user", "content": full_user_message})

print(f"\n总消息数: {len(messages)}")

# 调用模型
client = OpenAI(
    base_url="https://bobdong.cn/v1",
    api_key="sk-mHl9GZqWVufaySIDJM72Mvd3S4oL5o6X60PvJ29YjvEDXPeh"
)

print("\n" + "="*80)
print("正在调用模型...")
print("="*80)

response = client.chat.completions.create(
    model="GLM-5",
    messages=messages,
    temperature=0.0,
)

result = response.choices[0].message.content
print("\n" + "="*80)
print("模型输出:")
print("="*80)
print(result)

# 尝试解析 JSON
try:
    # 尝试提取 JSON
    json_match = re.search(r'\{[\s\S]*\}', result)
    if json_match:
        json_str = json_match.group(0)
        parsed = json.loads(json_str)
    else:
        parsed = json.loads(result)
    
    print("\n" + "="*80)
    print("解析后的 JSON:")
    print("="*80)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    
    # 检查别名使用
    alias_map = {
        "伯安": "伯安",
        "重明": "伯安",
        "贺伯安": "伯安",
        "三妈妈": "周凤兰",
        "周凤兰": "周凤兰",
        "二妈妈": "柳婉儿",
        "柳婉儿": "柳婉儿",
        "算盘": "林立果",
        "林立果": "林立果",
        "猴子": "侯飞白",
        "侯飞白": "侯飞白",
        "柱子": "柱子",
        "褚大山": "柱子",
    }
    
    print("\n" + "="*80)
    print("别名检查:")
    print("="*80)
    characters = parsed.get("characters", [])
    for char in characters:
        name = char.get("name", "")
        expected = alias_map.get(name, name)
        if name != expected:
            print(f"❌ 错误: {name} 应该是 {expected}")
        else:
            print(f"✓ 正确: {name}")
    
    # 检查是否有自环
    print("\n" + "="*80)
    print("关系检查:")
    print("="*80)
    relations = parsed.get("relations", [])
    for rel in relations:
        from_char = rel.get("from", "")
        to_char = rel.get("to", "")
        if from_char == to_char:
            print(f"❌ 自环: {from_char} -> {to_char}")
        else:
            print(f"✓ 关系: {from_char} -> {to_char}")
    
except json.JSONDecodeError as e:
    print(f"\nJSON 解析失败: {e}")
except Exception as e:
    print(f"\n处理失败: {e}")
