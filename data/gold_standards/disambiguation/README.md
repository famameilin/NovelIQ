# 消歧评测金标集

此目录存放人工标注的消歧金标准则。

## 文件格式

每个 run_id 对应一个 JSONL 文件（如 `6b401f00.jsonl`），每行一条记录：

```json
{
  "alias": "伯安",
  "canonical": "贺重明",
  "judgment": "should_merge",
  "evidence": "原文第23章'伯安，就叫字吧，名还是叫重明吧'",
  "annotator": "human",
  "annotated_at": "2026-04-01T00:00:00Z",
  "_meta": { ... }
}
```

## judgment 取值

| 值 | 含义 |
|----|------|
| `should_merge` | 应合并为同一角色 |
| `should_not_merge` | 应保持独立 |
| `ambiguous` | 人工也无法判断（不计入准确率） |

## 生成金标模板

```bash
uv run python -m scripts.tools.generate_gold_standard --run-ids 6b401f00,abededd4
```

生成后，逐条填写 `judgment`、`evidence`、`annotator`、`annotated_at` 字段。
`_meta` 字段为系统自动生成，请勿修改。

## 运行评测

```bash
uv run python -m scripts.tools.eval_disambig_baseline --run-ids 6b401f00,abededd4
```

## A/B 对比

```bash
uv run python -m scripts.tools.eval_disambig_baseline \
  --run-ids 6b401f00,abededd4 \
  --compare baseline_report.json
```
