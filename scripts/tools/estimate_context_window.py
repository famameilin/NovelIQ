"""
基于数据库实际数据估算本地模型每次调用的上下文窗口

说明: 从数据库查询实际的prompt/response数据，计算token使用量
      只计算本地模型（annotate + final_disambiguation），排除云端增量消歧
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.utils.token_counter import count_tokens  # noqa: E402

LOCAL_INTERACTION_TYPES = [
    ("annotate", "phase1"),
    ("annotate", "phase2"),
    ("disambiguate", "final_disambiguation"),
]


def estimate_from_db():
    """从数据库查询实际数据估算上下文窗口"""
    load_dotenv()
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("错误: 未找到 DATABASE_URL 环境变量")
        return
    
    engine = create_engine(database_url)
    
    print("=" * 70)
    print("本地模型上下文窗口估算报告（基于数据库实际数据）")
    print("=" * 70)
    print("\n说明: 只计算本地模型调用（annotate + final_disambiguation）")
    print("      排除云端增量消歧（incremental_disambiguation）")
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
              interaction_type,
              phase,
              model_provider,
              COUNT(*) as count,
              AVG(LENGTH(prompt)) as avg_prompt_chars,
              MAX(LENGTH(prompt)) as max_prompt_chars,
              MIN(LENGTH(prompt)) as min_prompt_chars,
              AVG(LENGTH(response)) as avg_response_chars,
              MAX(LENGTH(response)) as max_response_chars,
              AVG(LENGTH(COALESCE(thinking, ''))) as avg_thinking_chars,
              MAX(LENGTH(COALESCE(thinking, ''))) as max_thinking_chars
            FROM model_interactions 
            WHERE model_provider = 'local'
              AND NOT (interaction_type = 'disambiguate' AND phase = 'incremental_disambiguation')
            GROUP BY interaction_type, phase, model_provider
            ORDER BY interaction_type, phase
        """))
        
        stats = [dict(row._mapping) for row in result]
    
    print(f"\n数据库中共有 {sum(s['count'] for s in stats)} 条本地模型交互记录")
    print("\n" + "-" * 70)
    print("【各类型交互统计】")
    print("-" * 70)
    
    for s in stats:
        interaction_type = s['interaction_type']
        phase = s['phase']
        count = s['count']
        
        print(f"\n【{interaction_type} / {phase}】共 {count} 条记录")
        print(f"  Prompt 字符数: 平均 {s['avg_prompt_chars']:.0f}, 最大 {s['max_prompt_chars']}, 最小 {s['min_prompt_chars']}")
        print(f"  Response 字符数: 平均 {s['avg_response_chars']:.0f}, 最大 {s['max_response_chars']}")
        print(f"  Thinking 字符数: 平均 {s['avg_thinking_chars']:.0f}, 最大 {s['max_thinking_chars']}")
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
              interaction_type,
              phase,
              prompt,
              response,
              thinking
            FROM model_interactions 
            WHERE model_provider = 'local'
              AND NOT (interaction_type = 'disambiguate' AND phase = 'incremental_disambiguation')
            ORDER BY LENGTH(prompt) DESC
        """))
        
        all_interactions = [dict(row._mapping) for row in result]
    
    print("\n" + "=" * 70)
    print("【Token 估算（基于 tiktoken cl100k_base 编码器）】")
    print("=" * 70)
    
    token_stats = []
    for s in stats:
        interaction_type = s['interaction_type']
        phase = s['phase']
        
        interactions = [i for i in all_interactions 
                       if i['interaction_type'] == interaction_type and i['phase'] == phase]
        
        prompt_tokens = [count_tokens(i['prompt']) for i in interactions]
        response_tokens = [count_tokens(i['response']) for i in interactions]
        thinking_tokens = [count_tokens(i['thinking'] or '') for i in interactions]
        
        avg_prompt_tokens = sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else 0
        max_prompt_tokens = max(prompt_tokens) if prompt_tokens else 0
        min_prompt_tokens = min(prompt_tokens) if prompt_tokens else 0
        
        avg_response_tokens = sum(response_tokens) / len(response_tokens) if response_tokens else 0
        max_response_tokens = max(response_tokens) if response_tokens else 0
        
        avg_thinking_tokens = sum(thinking_tokens) / len(thinking_tokens) if thinking_tokens else 0
        max_thinking_tokens = max(thinking_tokens) if thinking_tokens else 0
        
        print(f"\n【{interaction_type} / {phase}】")
        print(f"  Prompt Tokens: 平均 {avg_prompt_tokens:.0f}, 最大 {max_prompt_tokens}, 最小 {min_prompt_tokens}")
        print(f"  Response Tokens: 平均 {avg_response_tokens:.0f}, 最大 {max_response_tokens}")
        print(f"  Thinking Tokens: 平均 {avg_thinking_tokens:.0f}, 最大 {max_thinking_tokens}")
        print(f"  总计 Tokens (平均): {avg_prompt_tokens + avg_response_tokens + avg_thinking_tokens:.0f}")
        print(f"  总计 Tokens (最大): {max_prompt_tokens + max_response_tokens + max_thinking_tokens}")
        
        token_stats.append({
            "type": f"{interaction_type}/{phase}",
            "count": s['count'],
            "avg_prompt_tokens": avg_prompt_tokens,
            "max_prompt_tokens": max_prompt_tokens,
            "min_prompt_tokens": min_prompt_tokens,
            "avg_response_tokens": avg_response_tokens,
            "max_response_tokens": max_response_tokens,
            "avg_thinking_tokens": avg_thinking_tokens,
            "max_thinking_tokens": max_thinking_tokens,
            "avg_total": avg_prompt_tokens + avg_response_tokens + avg_thinking_tokens,
            "max_total": max_prompt_tokens + max_response_tokens + max_thinking_tokens,
        })
    
    print("\n" + "=" * 70)
    print("【汇总表格】")
    print("=" * 70)
    print(f"\n{'任务类型':<40} {'记录数':<8} {'平均Prompt':<12} {'最大Prompt':<12} {'平均总计':<12} {'最大总计':<12}")
    print("-" * 96)
    for t in token_stats:
        print(f"{t['type']:<40} {t['count']:<8} {t['avg_prompt_tokens']:<12.0f} {t['max_prompt_tokens']:<12} {t['avg_total']:<12.0f} {t['max_total']:<12}")
    
    max_required = max(t['max_total'] for t in token_stats)
    max_prompt = max(t['max_prompt_tokens'] for t in token_stats)
    
    print("\n" + "=" * 70)
    print("【模型上下文窗口建议】")
    print("=" * 70)
    print(f"\n最大 Prompt Tokens: {max_prompt}")
    print(f"最大总 Tokens (含 Response): {max_required}")
    print(f"\n建议模型上下文窗口: >= {max_required * 1.5:.0f} tokens (预留50%余量)")
    print(f"推荐模型上下文窗口: >= {max_required * 2:.0f} tokens (预留100%余量)")
    
    print("\n【常见模型上下文窗口参考】")
    print("- Qwen2.5-7B/14B/32B: 32K tokens")
    print("- DeepSeek-V3: 64K tokens")
    print("- GPT-4 (8K版): 8K tokens")
    print("- GPT-4o: 128K tokens")
    print("- Claude-3: 200K tokens")
    
    return token_stats


if __name__ == "__main__":
    estimate_from_db()
