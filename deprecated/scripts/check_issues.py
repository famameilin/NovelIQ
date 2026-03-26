"""
对照问题报告检查JSON修复状态
2026-03-11 创建
"""
import json

data = json.load(open(r'E:\projects\python-projects\novel quantitative analysis\outputs\ed83162a.json', 'r', encoding='utf-8'))

print('=== 对照问题报告检查修复状态 ===\n')

# 问题1: chunk_annotations 缺失关键字段
print('【问题1】chunk_annotations 缺失关键字段')
ann = data.get('chunk_annotations', [])[0] if data.get('chunk_annotations') else {}
has_chars = 'characters' in ann
has_rels = 'relations' in ann
has_dialogs = 'dialogues' in ann
print(f'  characters字段: {"存在" if has_chars else "缺失"}')
print(f'  relations字段: {"存在" if has_rels else "缺失"}')
print(f'  dialogues字段: {"存在" if has_dialogs else "缺失"}')
print(f'  状态: {"已修复" if has_chars and has_rels and has_dialogs else "未修复"}')

# 问题2: tone_distribution 字段污染
print('\n【问题2】tone_distribution 字段污染')
style = data.get('aggregate_metrics', {}).get('style_stats', {})
print(f'  style_stats keys: {list(style.keys()) if style else "无"}')
tone_dist = style.get('tone_distribution')
print(f'  tone_distribution: {tone_dist}')
print(f'  状态: {"已修复" if isinstance(tone_dist, dict) and "强硬" in str(tone_dist) else "未修复"}')

# 问题3: greimas_coverage 字段含义错误
print('\n【问题3】greimas_coverage 字段含义错误')
char_stats = data.get('aggregate_metrics', {}).get('character_stats', {})
greimas = char_stats.get('greimas_coverage')
print(f'  greimas_coverage: {greimas}')
print(f'  类型: {type(greimas).__name__}')
print(f'  状态: {"已修复" if isinstance(greimas, (int, float)) else "未修复"}')

# 问题4: avg_word_len = 8.64
print('\n【问题4】avg_word_len 计算错误')
avg_word = style.get('avg_word_len')
print(f'  avg_word_len: {avg_word}')
print(f'  状态: {"已修复" if avg_word and avg_word < 3 else "未修复"}')

# 问题5: idiom_density = 0.689
print('\n【问题5】idiom_density 计算错误')
culture = data.get('aggregate_metrics', {}).get('culture_stats', {})
idiom = culture.get('idiom_density')
print(f'  idiom_density: {idiom}')
print(f'  状态: {"已修复" if idiom and idiom < 0.1 else "未修复"}')

# 问题6: recovery_speed = 0.0
print('\n【问题6】recovery_speed 返回值问题')
emotion_stats = data.get('aggregate_metrics', {}).get('emotion_stats', {})
recovery = emotion_stats.get('recovery_speed')
print(f'  recovery_speed: {recovery}')
print(f'  状态: {"已修复" if recovery is not None and recovery > 0 else "未修复"}')

# 问题7: novel_name = task_id
print('\n【问题7】novel_name 字段错误')
print(f'  novel_name: {data.get("novel_name")}')
print(f'  状态: {"已修复" if data.get("novel_name") not in ["ed83162a", "86fe028a"] else "未修复"}')

# 问题8: arc_scores 无人物名称映射
print('\n【问题8】arc_scores 无人物名称映射')
diag = data.get('diagnosis', {})
arc = diag.get('arc_scores')
print(f'  arc_scores: {arc}')
print(f'  状态: {"已修复" if isinstance(arc, dict) else "未修复"}')

# 问题9: emotion_curve_type 非规范值
print('\n【问题9】emotion_curve_type 非规范值')
curve_type = emotion_stats.get('emotion_curve_type')
valid_types = ['白手起家', '伊卡洛斯', '落坑爬出', '持续下降', '灰姑娘', '俄狄浦斯']
print(f'  emotion_curve_type: {curve_type}')
print(f'  状态: {"已修复" if curve_type in valid_types else "未修复"}')

# 问题10: character_relations 中存在自环
print('\n【问题10】character_relations 中存在自环')
relations = data.get('character_relations', [])
self_loops = [r for r in relations if r.get('from_char') == r.get('to_char')]
print(f'  自环数量: {len(self_loops)}')
if self_loops:
    print(f'  自环示例: {self_loops[0]}')
print(f'  状态: {"已修复" if len(self_loops) == 0 else "未修复"}')

# 问题11: topics 中出现 "..." 词条
print('\n【问题11】topics 中出现标点词条')
topics = data.get('topics', [])
punct_topics = []
for t in topics:
    words = t.get('words', [])
    punct_words = [w for w in words if w in ['...', '…', '。', '，', '！', '？']]
    if punct_words:
        punct_topics.append((t.get('topic_id'), punct_words))
print(f'  含标点的主题数: {len(punct_topics)}')
print(f'  状态: {"已修复" if len(punct_topics) == 0 else "未修复"}')

print('\n=== 检查完成 ===')
