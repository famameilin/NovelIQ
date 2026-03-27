from src.models.diagnosis import DiagnosisClient


def test_build_messages_uses_alias_merges_and_known_characters():
    client = object.__new__(DiagnosisClient)

    messages = client._build_messages(
        {
            "novel_id": "novel-1",
            "known_characters": ["bai_zhi", "hou_fei_bai"],
            "alias_merges": {
                "masked_person": "bai_zhi",
                "monkey": "hou_fei_bai",
            },
        }
    )

    system_message = messages[0]["content"]

    assert "Naming rules:" in system_message
    assert "alias_merges" in system_message
    assert '"masked_person": "bai_zhi"' in system_message
    assert '"monkey": "hou_fei_bai"' in system_message
    assert "known_characters" in system_message
