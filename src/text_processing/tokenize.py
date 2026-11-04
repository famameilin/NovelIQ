from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from itertools import accumulate
from pathlib import Path
from types import ModuleType

from loguru import logger

from src.lexicons.constants import LEXICON_FILES

_LEXICON_DIR = Path("data/lexicons")
_request_token_blocks: ContextVar[dict[str, tuple[str, ...]] | None] = ContextVar("request_token_blocks", default=None)


@contextmanager
def reuse_token_blocks() -> Iterator[None]:
    """在单次计算内复用相同词法块的原始词元"""
    token = _request_token_blocks.set({})
    try:
        yield
    finally:
        _request_token_blocks.reset(token)


def _default_user_dict_path() -> Path:
    return _LEXICON_DIR / LEXICON_FILES["jieba_user_dict"]


def _default_stopwords_path() -> Path:
    return _LEXICON_DIR / LEXICON_FILES["stopwords"]


# 融合词在运行时删除：基础词典低频词需 del_word，HMM 模型词由 force_split 阻断合并；
# 覆盖 副词×情绪字×{裸/了/的} 全矩阵；爱 类刻意不删（习惯性偏好漂移：最爱说/太爱装）。
_ADVERB_PREFIXES = ("很", "太", "好", "超", "巨", "特", "挺", "蛮", "更", "最", "极", "颇", "愈", "贼")
_EMOTION_SINGLE_CHARS = ("爽", "慌")
_EMOTION_FUSION_SPLITS = tuple(
    a + c + suffix for a in _ADVERB_PREFIXES for c in _EMOTION_SINGLE_CHARS for suffix in ("", "了", "的")
) + ("爽得", "爽到", "慌得", "慌到")


class Tokenizer:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        user_dict_path: Path | None = None,
        stopwords_path: Path | None = None,
        min_word_len: int = 1,
    ) -> None:
        if Tokenizer._initialized:
            return
        self._user_dict_path = user_dict_path
        self._stopwords_path = stopwords_path
        self._min_word_len = min_word_len
        self._stopwords: set[str] = set()
        self._jieba: ModuleType | None = None
        self._load_jieba()
        self._load_stopwords()
        self._load_user_dict()
        Tokenizer._initialized = True

    def _load_jieba(self) -> None:
        try:
            import jieba

            self._jieba = jieba
            jieba.setLogLevel(jieba.logging.INFO)
        except ImportError:
            logger.warning("jieba未安装，分词功能将使用简单正则替代")
            self._jieba = None

    def _load_stopwords(self) -> None:
        if not self._stopwords_path:
            return
        if not self._stopwords_path.exists():
            logger.warning("停用词文件不存在: {}", self._stopwords_path)
            return
        try:
            with open(self._stopwords_path, encoding="utf-8") as f:
                self._stopwords = {line.strip() for line in f if line.strip()}
            logger.debug("加载停用词: 数量={}", len(self._stopwords))
        except Exception as e:
            logger.warning("加载停用词失败: {}", e)
            self._stopwords = set()

    def _load_user_dict(self) -> None:
        if not self._jieba:
            return
        if not self._user_dict_path:
            default_path = _default_user_dict_path()
            if default_path.exists():
                self._user_dict_path = default_path
            else:
                return
        if self._user_dict_path and self._user_dict_path.exists():
            self._jieba.load_userdict(str(self._user_dict_path))
            logger.debug("加载jieba用户词典: {}", self._user_dict_path)
        # 删除融合词路由：基础词典低频词需运行时移除；HMM 模型词由用户词典 freq=0 强制切分
        for word in _EMOTION_FUSION_SPLITS:
            self._jieba.del_word(word)

    def tokenize(self, text: str, filter_stopwords: bool = False) -> list[str]:
        if not text or not text.strip():
            return []
        if self._jieba:
            tokens = self._jieba.lcut(text) if _request_token_blocks.get() is None else list(self._cut(text))
        else:
            import re

            tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text)
        return self._filter_tokens(tokens, filter_stopwords)

    def _cut(self, text: str) -> Iterator[str]:
        jieba = self._jieba
        if jieba is None:
            raise RuntimeError("分词器不可用")
        blocks = _request_token_blocks.get()
        if blocks is None:
            yield from jieba.cut(text)
            return
        for block in jieba.re_han_default.split(text):
            if not block:
                continue
            if jieba.re_han_default.fullmatch(block):
                tokens = blocks.get(block)
                if tokens is None:
                    tokens = blocks[block] = tuple(jieba.cut(block))
                yield from tokens
            else:
                yield from jieba.cut(block)

    def _filter_tokens(self, tokens: list[str], filter_stopwords: bool = False) -> list[str]:
        result = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if len(token) < self._min_word_len:
                continue
            if filter_stopwords and token in self._stopwords:
                continue
            result.append(token)
        return result

    def tokenize_with_word_lengths(self, text: str) -> tuple[list[str], int, int]:
        """同时返回标准词元、去空白词数和未裁剪词长之和"""
        if not self._jieba:
            tokens = self.tokenize(text)
            return tokens, len(tokens), sum(map(len, tokens))
        raw_tokens = [word for word in self._cut(text) if word.strip()]
        return self._filter_tokens(raw_tokens), len(raw_tokens), sum(map(len, raw_tokens))

    def tokenize_chapters_and_book(self, chapters: list[str]) -> tuple[list[list[str]], list[str]]:
        """共享章内分词，跨章词法块分别按章和全书口径计算"""
        book = "".join(chapters)
        if not self._jieba:
            return [self.tokenize(text) for text in chapters], self.tokenize(book)

        chapter_ends = list(accumulate(len(text) for text in chapters))
        chapter_tokens: list[list[str]] = [[] for _ in chapters]
        book_tokens: list[str] = []

        def tokenize_parts(start: int, end: int, *, share_with_book: bool) -> None:
            while start < end:
                chapter = bisect_right(chapter_ends, start)
                part_end = min(chapter_ends[chapter], end)
                tokens = self.tokenize(book[start:part_end])
                chapter_tokens[chapter].extend(tokens)
                if share_with_book:
                    book_tokens.extend(tokens)
                start = part_end

        cursor = 0
        # Jieba 独立切分每个词法块，块外跨章的换行和空白会被过滤
        for block in self._jieba.re_han_default.finditer(book):
            start, end = block.span()
            if chapter_ends[bisect_right(chapter_ends, start)] >= end:
                continue
            tokenize_parts(cursor, start, share_with_book=True)
            tokenize_parts(start, end, share_with_book=False)
            book_tokens.extend(self.tokenize(block.group()))
            cursor = end
        tokenize_parts(cursor, len(book), share_with_book=True)
        return chapter_tokens, book_tokens

    def add_stopwords(self, words: list[str]) -> None:
        for word in words:
            self._stopwords.add(word)

    @property
    def stopwords(self) -> set[str]:
        return self._stopwords.copy()


_tokenizer: Tokenizer | None = None


def is_tokenizer_initialized() -> bool:
    return _tokenizer is not None


def get_tokenizer(
    user_dict_path: Path | None = None,
    stopwords_path: Path | None = None,
    min_word_len: int = 1,
) -> Tokenizer:
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer(
            user_dict_path=user_dict_path,
            stopwords_path=stopwords_path,
            min_word_len=min_word_len,
        )
    return _tokenizer


def tokenize(text: str, filter_stopwords: bool = False) -> list[str]:
    return get_tokenizer().tokenize(text, filter_stopwords=filter_stopwords)
