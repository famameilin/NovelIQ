from __future__ import annotations

from typing import Any

from .types import GraphAuthorityReport


def serialize_graph_report_signals(graph_report: GraphAuthorityReport) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Serialize shared graph-owned signals for diagnosis/export consumers

    这里是 diagnosis/export 复用 graph signals 的唯一共享入口，
    调用方必须显式传入 GraphAuthorityReport，不能绕过 report 去序列化
    GraphAuthorityView 或 graph page 专属 contract
    """

    if type(graph_report) is not GraphAuthorityReport:
        raise TypeError(
            f"shared graph signal consumers require GraphAuthorityReport; got {type(graph_report).__name__}"
        )
    return graph_report.summary.to_contract_dict(), graph_report.quality.to_contract_dict()
