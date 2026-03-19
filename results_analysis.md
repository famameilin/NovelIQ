# 分析结果 JSON 结构说明

## 文件信息
- **生成时间**: 2026-03-19T01:53:18
- **任务ID**: 95cf29d5-d649-4173-a285-2693c9adca5a
- **小说ID**: d3b3594f
- **小说名称**: list_test

## JSON 结构概览

```json
{
  "task_id": "分析任务唯一标识",
  "novel_id": "小说唯一标识",
  "novel_name": "小说名称",
  "generated_at": "结果生成时间",
  "total_chunks": 分块数量,
  "total_chars": 总字符数,
  "emotion_curve": [],  // 情感曲线数据
  "rhythm_curve": [],   // 节奏曲线数据
  "characters": [],     // 人物列表
  "topics": [],         // 主题列表
  "diagnosis": null,    // 诊断结果
  "chunk_styles": [],   // 分块风格分析
  "chunk_annotations": [], // 分块标注详情
  "character_relations": [], // 人物关系
  "global_stats": null, // 全局统计
  "chunk_cultures": [], // 分块文化内涵
  "aggregate_metrics": { // 聚合指标
    "narrative_structure": { ... },  // 叙事结构
    "emotion_stats": { ... },        // 情感统计
    "character_stats": { ... },      // 人物统计
    "style_stats": { ... },          // 风格统计
    "culture_stats": { ... }         // 文化统计
  },
  "token_usage_stats": { // Token 使用统计
    "summary": { ... },
    "by_task": { ... },
    "by_model": { ... }
  }
}
```

## 关键字段详解

### 1. 叙事结构 (narrative_structure)
```json
{
  "act1_ratio": 0.0,        // 第一幕占比
  "act2_ratio": 0.0,        // 第二幕占比
  "act3_ratio": 0.0,        // 第三幕占比
  "climax_spacing": 0.0,    // 高潮间距
  "middle_collapse_index": 0.0, // 中段崩溃指数
  "event_density": {         // 事件密度
    "冲突": 0.0,
    "铺垫": 0.0,
    "转折": 0.0
  },
  "cliffhanger_rate": 0.0   // 悬念率
}
```

### 2. 情感统计 (emotion_stats)
```json
{
  "pos_neg_ratio": 0.0,      // 正负情感比例
  "positive_ratio": 0.0,     // 正面情感占比
  "negative_ratio": 0.0,     // 负面情感占比
  "neutral_ratio": 0.0,      // 中性情感占比
  "recovery_speed": null,    // 情感恢复速度
  "pivot_moment_density": 0.0, // 转折点密度
  "emotion_curve_type": "白手起家" // 情感曲线类型
}
```

### 3. 人物统计 (character_stats)
```json
{
  "network_density": 0.0,           // 人物网络密度
  "protagonist_betweenness": null,  // 主角中介中心性
  "greimas_coverage": 0.0,          // 格雷马斯角色覆盖度
  "function_coverage_distribution": { // 角色功能分布
    "主体": 0.0,
    "客体": 0.0,
    "发送者": 0.0,
    "接收者": 0.0,
    "帮助者": 0.0,
    "反对者": 0.0,
    "其他": 0.0
  },
  "antagonist_strength_gap": 0.0,   // 正反派实力差距
  "relation_change_freq": 0.0,      // 关系变化频率
  "degree_centrality": null         // 度中心性
}
```

### 4. 风格统计 (style_stats)
```json
{
  "tone_distribution": null,   // 语气分布
  "vocab_breadth": 0.0,        // 词汇广度
  "avg_word_len": 0.0,         // 平均词长
  "sent_len_std": 0.0,         // 句长标准差
  "function_word_vector": {     // 功能词向量（18个文言虚词）
    "之": 0.0, "乎": 0.0, "者": 0.0, ...
  },
  "category_density": {         // 词类密度
    "人物": 0.0, "自然": 0.0, "器物": 0.0, ...
  }
}
```

### 5. 文化统计 (culture_stats)
```json
{
  "confucian_density": null,      // 儒家文化密度
  "taoist_density": null,         // 道家文化密度
  "buddhist_density": null,       // 佛家文化密度
  "folk_density": null,           // 民俗文化密度
  "allusion_density": null,       // 典故密度
  "idiom_density": 0.0,           // 成语密度
  "classical_sentence_ratio": 0.0, // 文言句式比例
  "imagery_density": null         // 意象密度
}
```

### 6. Token 使用统计 (token_usage_stats)
```json
{
  "summary": {
    "call_count": 0,              // 调用次数
    "total_prompt_tokens": 0,     // 总提示词 Token
    "total_completion_tokens": 0, // 总生成 Token
    "total_tokens": 0             // 总 Token
  },
  "by_task": {},    // 按任务类型统计
  "by_model": {}    // 按模型统计
}
```

## 当前结果状态

**注意**: 当前结果文件显示的是测试数据：
- `total_chunks`: 0
- `total_chars`: 0
- 大部分字段为空或默认值

这是因为测试文件没有实际内容。实际分析结果会包含：
- 情感曲线和节奏曲线的具体数值
- 人物列表及其属性
- 主题分析结果
- 诊断报告
- 分块级别的详细标注
- 人物关系网络
- 文化内涵分析

## 缺失字段

当前结果中缺失以下字段（将在完整分析后填充）：
- `emotion_curve` - 情感曲线
- `rhythm_curve` - 节奏曲线
- `characters` - 人物列表
- `diagnosis` - 诊断结果
- `chunk_styles` - 分块风格
- `chunk_annotations` - 分块标注
