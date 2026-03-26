"""
问题#6 根本原因分析
2026-03-11 创建
"""

print('=== 问题#6 根本原因分析 ===\n')

# 实际数据
emotion_range = (-0.0087, 0.0087)
baseline = -0.0009
threshold = 0.3  # 配置文件中的阈值

print('【数据量级】')
print(f'  情感值范围: {emotion_range[0]:.4f} ~ {emotion_range[1]:.4f}')
print(f'  情感值均值: {baseline:.4f}')

print('\n【阈值配置】')
print(f'  emotion_recovery_threshold: {threshold}')

print('\n【判定线计算】')
print(f'  负向判定线 = baseline - threshold = {baseline:.4f} - {threshold} = {baseline - threshold:.4f}')
print(f'  恢复判定线 = baseline - threshold * 0.5 = {baseline - threshold * 0.5:.4f}')

print('\n【问题诊断】')
print(f'  情感值最小值: {emotion_range[0]:.4f}')
print(f'  负向判定线: {baseline - threshold:.4f}')
print(f'  最小值 > 判定线? {emotion_range[0] > baseline - threshold}')
print()
print('  结论: 阈值 0.3 远大于情感值量级 (~0.01)')
print('        所有情感值都高于负向判定线')
print('        因此没有负向块被识别')
print('        recovery_speed = None 是必然结果')

print('\n【根本原因】')
print('  阈值 0.3 是针对归一化情感值 (-1 到 1) 设计的')
print('  但 net_density 实际范围只有 -0.01 到 0.01')
print('  阈值与数据量级不匹配！')

print('\n【修复建议】')
print('  方案1: 将阈值改为 0.005 或更小的值')
print('  方案2: 在计算时动态调整阈值（基于数据标准差）')
print('  方案3: 归一化 net_density 到 -1 到 1 范围')
