# 废弃词表文件

此目录存放已废弃的词表文件，保留用于历史参考。

## 文件说明

| 文件 | 说明 | 废弃时间 |
|------|------|----------|
| allusion.txt | 典故词表 | 2026-03-26 |
| buddhism.txt | 佛家词表 | 2026-03-26 |
| confucian.txt | 儒家词表 | 2026-03-26 |
| dao.txt | 道家词表 | 2026-03-26 |
| folk.txt | 民俗词表 | 2026-03-26 |

## 废弃原因

这些词表密度指标被评估为低价值指标，在简化文化指标系统时被移除。

保留的文化指标：
- 成语密度 (idiom_density)
- 文言句式比例 (classical_sentence_ratio)
- 意象密度 (imagery_density)

## 相关任务

- 任务: 简化文化指标系统
- 分支: feature/expand-culture-lexicons
- 提交: refactor: 简化文化指标系统，删除低价值词表密度指标
