"""将冻结诊断候选一次发布到新关系，源声明保持不可变（2026-10-16 全库 3NF 改造）

- 完整事件：complete_events（身份 + 真实生产者 + 同一性理由）
- 阶段版本：event_revisions 的显式连续 stage_index 链（绑定声明或独立 origin 正文恰一）
- 包含/关系：narrative_links 的单父包含形状与语义关系形状，证据进 source_evidence
- 组织核对：organization_checks 的单事件/单声明核对与声明对/结构对判断四类形状
伏笔 root/target 不在此回填：正式读取经阶段声明绑定投影；情节推进同样经声明引用读取。
"""
