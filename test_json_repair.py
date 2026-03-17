"""测试 json-repair 库处理不完整 JSON 的能力"""
from json_repair import repair_json

# 测试不完整的 JSON
test_cases = [
    '{"name": "张三", "age":',
    '{"name": "张三", "age": 25',
    '{"name": "张三", "age": 25, "city":',
    '{"characters": [{"name": "张三", "role": "主角',
]

for i, test in enumerate(test_cases, 1):
    print(f'测试 {i}: {test}')
    try:
        result = repair_json(test)
        print(f'结果: {result}')
    except Exception as e:
        print(f'错误: {e}')
    print()
