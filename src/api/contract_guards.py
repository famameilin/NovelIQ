"""
段落合同门（设计文档《章节粒度分析指标重设计》§16）

旧 run（analysis_contract_version 非 paragraph-v1）没有段落事实源数据，
所有段落数据源接口统一在此短路为 409，要求重新分析，不静默返回空数据。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def require_paragraph_contract(run: dict[str, Any]) -> None:
    """段落级接口的合同版本门：旧 run 直接 409 要求重新分析。"""
    if run.get("analysis_contract_version") != "paragraph-v1":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "paragraph_contract_rerun_required",
                "message": "当前任务的段落分析合同已失效（旧版 run 无段落事实源），请重新分析。",
                "reason": f"analysis_contract_version={run.get('analysis_contract_version')!r}",
            },
        )
