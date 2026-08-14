"""诊断 Agent 证据调用账本"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DiagnosisEvidenceLedger:
    """诊断 Agent 本轮工具取证记录"""

    tool_calls: list[str] = field(default_factory=list)

    def record_tool_call(self, tool_name: str) -> None:
        """
        2026-08-04 用于按调用顺序登记诊断证据工具名称
        """
        self.tool_calls.append(tool_name)

    def require_evidence(self) -> None:
        """
        2026-08-04 用于阻止未执行任何取证工具的诊断结果提交
        """
        if not self.tool_calls:
            raise ValueError("diagnosis finish 前必须至少调用一个证据工具")

    def to_dict(self) -> dict[str, list[str]]:
        """
        2026-08-04 用于生成诊断模型交互审计中的证据来源载荷
        """
        return {"tool_calls": list(self.tool_calls)}
