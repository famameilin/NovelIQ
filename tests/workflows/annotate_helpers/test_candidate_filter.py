"""
CandidateFilter 单元测试

创建时间: 2026-04-20
创建者: Codex
任务: preserve-deferred-disambig-candidates
说明: 锁定候选过滤的关键边界，避免低频正式名再次被当作噪音直接蒸发。
"""

from src.workflows.annotate_helpers.disambiguation.candidate_filter import CandidateFilter


def test_candidate_filter_defers_low_frequency_name_without_context() -> None:
    """
    创建时间: 2026-04-20
    创建者: Codex
    任务: preserve-deferred-disambig-candidates
    说明: 低频且暂无上下文的正式名字应延后处理，而不是直接丢弃。
    """
    candidate_filter = CandidateFilter()

    result = candidate_filter.classify("侯飞白", count=1, has_context=False)

    assert result.category == "deferred"
    assert "延后处理" in result.reason


def test_candidate_filter_keeps_protected_name_for_model_review() -> None:
    """
    创建时间: 2026-04-20
    创建者: Codex
    任务: preserve-deferred-disambig-candidates
    说明: 受保护名单中的通用职位仍应保留送消歧，不能退回到硬删除。
    """
    candidate_filter = CandidateFilter()

    result = candidate_filter.classify("侍卫", count=1, has_context=False)

    assert result.category == "protected"
    assert result.reason == "精确匹配受保护名单"


def test_candidate_filter_blacklists_obvious_noise_token() -> None:
    """
    创建时间: 2026-04-20
    创建者: Codex
    任务: preserve-deferred-disambig-candidates
    说明: 只有明显脏 token 才允许走硬丢弃。
    """
    candidate_filter = CandidateFilter()

    result = candidate_filter.classify("12345", count=1, has_context=False)

    assert result.category == "blacklist"
    assert "明显脏 token" in result.reason


def test_candidate_filter_marks_pronoun_as_reference_candidate() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 代词需要保留给消歧解析，但不能作为普通 canonical 候选进入主链。
    """
    candidate_filter = CandidateFilter()

    result = candidate_filter.classify("她", count=1, has_context=False)

    assert result.category == "reference"
    assert "角色引用" in result.reason
