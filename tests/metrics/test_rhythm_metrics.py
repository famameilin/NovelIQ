"""
张力代理指标测试（fuzzy 模式）

创建时间: 2026-04-06
创建者: GLM-5
任务: 词表与张力信号系统重构 - Task 6
说明: 测试 tension_proxy 使用 fuzzy 模式匹配分词变体
修改时间: 2026-04-06
修改者: GLM-5
修改内容: 更新参数类型为 dict[str, int]
"""
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.rhythm_metrics import tension_proxy


class TestTensionProxyFuzzyMode(unittest.TestCase):
    """
    测试张力代理指标的 fuzzy 模式匹配

    fuzzy 模式支持:
    - token 级匹配（如"剑气"）
    - 子串匹配（如"冷笑"被分词为"冷"+"笑"时仍能匹配）
    - 编辑距离容错（如"剑罡"匹配"剑气"，编辑距离=1）
    """

    def test_empty_text(self) -> None:
        """空文本返回零值"""
        result = tension_proxy("", {"剑气": 1})
        self.assertEqual(result["fight_density"], 0.0)
        self.assertEqual(result["dialogue_ratio"], 0.0)

    def test_basic_token_match(self) -> None:
        """基本 token 匹配"""
        result = tension_proxy("剑气纵横", {"剑气": 1})
        self.assertGreater(result["fight_density"], 0.0)

    def test_fuzzy_match_variant(self) -> None:
        """
        fuzzy 模式匹配分词变体

        场景: 词表中有"攻击"，文本中出现"进击"
        jieba 分词: ['进击', '敌人']
        编辑距离: 攻击 vs 进击 = 1 (仅替换一个字)
        期望: fuzzy 模式能匹配
        """
        result = tension_proxy("进击敌人", {"攻击": 1})
        self.assertGreater(result["fight_density"], 0.0)

    def test_fuzzy_match_similar_term(self) -> None:
        """
        fuzzy 模式匹配相似词（编辑距离=2，不应匹配）

        场景: 词表中有"剑气"，文本中出现"霸剑"
        jieba 分词: ['霸剑']
        编辑距离: 剑气 vs 霸剑 = 2 (剑->霸 + 气->剑)
        注意: 默认 max_edit_distance=1，此 case 不应匹配
        """
        result = tension_proxy("霸剑纵横", {"剑气": 1})
        self.assertEqual(result["fight_density"], 0.0)

    def test_phrase_match_in_text(self) -> None:
        """
        phrase 模式匹配文本中的词（fuzzy 包含 phrase）

        场景: 词表中有"战斗"，文本中包含该词
        期望: 能匹配
        """
        result = tension_proxy("这是一场激烈的战斗", {"战斗": 1})
        self.assertGreater(result["fight_density"], 0.0)

    def test_exclaim_density(self) -> None:
        """感叹号密度计算"""
        result = tension_proxy("太棒了！真的太棒了！", {})
        self.assertGreater(result["exclaim_density"], 0.0)

    def test_question_density(self) -> None:
        """问号密度计算"""
        result = tension_proxy("为什么？怎么会这样？", {})
        self.assertGreater(result["question_density"], 0.0)

    def test_dialogue_ratio(self) -> None:
        """对话比例计算"""
        result = tension_proxy('他说："你好！"', {})
        self.assertGreater(result["dialogue_ratio"], 0.0)

    def test_multiple_fight_terms(self) -> None:
        """多个战斗词匹配"""
        result = tension_proxy("剑气纵横，刀光剑影", {"剑气": 1, "刀光": 1})
        self.assertGreater(result["fight_density"], 0.0)


if __name__ == "__main__":
    unittest.main()
