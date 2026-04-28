"""
修复 model_interactions 表的外键约束问题

问题描述:
model_interactions_chunk_id_run_id_fkey 外键约束定义错误，
将 chunk_id 映射到了 chunks.run_id，将 run_id 映射到了 chunks.chunk_id。

修复方案:
1. 删除错误的外键
