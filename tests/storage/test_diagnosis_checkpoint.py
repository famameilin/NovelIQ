import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.storage.repositories.diagnosis_repository import DiagnosisRepository


def test_fetch_character_disambig_data_reads_identity_memory_alias_map() -> None:
    """
    2026-08-02 用于保证诊断人物工具读取当前 checkpoint 的 alias_map
    """
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = SimpleNamespace(
        state_json=json.dumps(
            {
                "known_canonical_names": ["顾霜"],
                "alias_map": {
                    "阿顾": "顾霜",
                    "我": "顾霜",
                    "顾霜": "顾霜",
                },
            },
            ensure_ascii=False,
        )
    )

    known, aliases = DiagnosisRepository(session).fetch_character_disambig_data("run-1")

    assert known == ["顾霜"]
    assert aliases == {"阿顾": "顾霜"}


def test_fetch_character_disambig_data_rejects_obsolete_checkpoint_shape() -> None:
    """
    2026-08-02 用于拒绝当前诊断链路读取废弃的 alias_merges 结构
    """
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = SimpleNamespace(
        state_json=json.dumps(
            {
                "known_canonical_names": ["顾霜"],
                "alias_merges": [["阿顾", "顾霜"]],
            },
            ensure_ascii=False,
        )
    )

    with pytest.raises(ValueError, match="alias_map"):
        DiagnosisRepository(session).fetch_character_disambig_data("run-1")
