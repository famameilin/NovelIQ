
filepath = r'e:\projects\python-projects\novel quantitative analysis\data\lexicons\stopwords.txt'

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

result_lines = []
seen_words = set()
removed = []

for line in lines:
    stripped = line.strip()
    
    if not stripped or stripped.startswith('#'):
        result_lines.append(line)
        continue
    
    if stripped in seen_words:
        removed.append(stripped)
        continue
    
    seen_words.add(stripped)
    result_lines.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(result_lines)

print(f'删除重复词条: {len(removed)}个')
print(f'删除内容: {removed}')
print(f'保留词条: {len(seen_words)}个')
