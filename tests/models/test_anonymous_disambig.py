"""
测试匿名人物消歧功能

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 移除 sqlite3.connect mock，使用 MagicMock 模拟连接
"""
import re
import unittest
from unittest.mock import MagicMock


class TestBuildAnonymousContexts(unittest.TestCase):
    def test_anonymous_name_regex(self) -> None:
        pattern = r'^匿名_C\d+_\d+$'
        self.assertTrue(re.match(pattern, '匿名_C1_0'))
        self.assertTrue(re.match(pattern, '匿名_C123_45'))
        self.assertFalse(re.match(pattern, '匿名_1_0'))
        self.assertFalse(re.match(pattern, '匿名C1_0'))
        self.assertFalse(re.match(pattern, '张三'))
    
    def test_extract_chunk_id(self) -> None:
        match = re.match(r'^匿名_C(\d+)_\d+$', '匿名_C5_2')
        self.assertIsNotNone(match)
        if match:
            chunk_id = int(match.group(1))
            self.assertEqual(chunk_id, 5)
    
    def test_build_anonymous_contexts(self) -> None:
        from src.workflows.annotate_helpers.disambiguation import build_anonymous_contexts
        
        mock_conn = MagicMock()
        
        def mock_execute(query, params=None):
            if params is None:
                return MagicMock(fetchone=lambda: None)
            chunk_id = params.get('chunk_id', 0) if isinstance(params, dict) else (params[0] if isinstance(params, tuple) else 0)
            if chunk_id == 2:
                return MagicMock(fetchone=lambda: ('当前块文本',))
            elif chunk_id == 1:
                return MagicMock(fetchone=lambda: ('前一块文本',))
            elif chunk_id == 3:
                return MagicMock(fetchone=lambda: ('后一块文本',))
            return MagicMock(fetchone=lambda: None)
        
        mock_conn.execute = mock_execute
        
        contexts = build_anonymous_contexts(mock_conn, ['匿名_C2_0'])
        
        self.assertIn('匿名_C2_0', contexts)
        self.assertIn('[前文]', contexts['匿名_C2_0'])
        self.assertIn('[当前段落]', contexts['匿名_C2_0'])
        self.assertIn('[后文]', contexts['匿名_C2_0'])
        self.assertIn('前一块文本', contexts['匿名_C2_0'])
        self.assertIn('当前块文本', contexts['匿名_C2_0'])
        self.assertIn('后一块文本', contexts['匿名_C2_0'])


class TestAnonymousDisambigMessages(unittest.TestCase):
    def test_build_messages_format(self) -> None:
        from src.models.local.unified_client import UnifiedModelClient
        from src.config.input_config import TaskModelConfig
        
        config = TaskModelConfig(
            model='test-model',
            base_url='http://localhost:8000',
            api_key='test',
        )
        client = UnifiedModelClient(config=config, task_type='test')
        
        messages = client._build_anonymous_disambig_messages(
            anonymous_names=['匿名_C1_0', '匿名_C3_1'],
            anonymous_contexts={
                '匿名_C1_0': '[前文]\n...\n[当前段落]\n测试文本\n[后文]\n...',
                '匿名_C3_1': '[前文]\n...\n[当前段落]\n另一段文本\n[后文]\n...',
            },
            existing_names=['张三', '李四'],
            existing_contexts={'张三': '张三走进房间', '李四': '李四站在门口'},
        )
        
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(messages[1]['role'], 'user')
        self.assertIn('匿名_C1_0', messages[1]['content'])
        self.assertIn('匿名_C3_1', messages[1]['content'])
        self.assertIn('张三（参考：张三走进房间）', messages[1]['content'])
        self.assertIn('李四（参考：李四站在门口）', messages[1]['content'])
        self.assertIn('【匿名人物】', messages[1]['content'])


if __name__ == '__main__':
    unittest.main()
