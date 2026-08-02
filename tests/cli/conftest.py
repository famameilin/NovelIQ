"""
CLI 测试公共配置

说明: 旧版 FakeClient / FakeLocalModelClient 随阶段 1-4 与消歧流程移除，
     标注/诊断均已 agent 化，测试通过 patch agent 入口实现
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
