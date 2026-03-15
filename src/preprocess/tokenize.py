from __future__ import annotations

from pathlib import Path
from typing import List, Set

from loguru import logger


def _default_user_dict_path() -> Path:
    return Path("data/lexicons/jieba_user_dict.txt")


def _default_stopwords_path() -> Path:
    return Path("data/lexicons/stopwords.txt")


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
        self._stopwords: Set[str] = set()
        self._jieba = None
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
            with open(self._stopwords_path, "r", encoding="utf-8") as f:
                self._stopwords = set(line.strip() for line in f if line.strip())
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

    def tokenize(self, text: str, filter_stopwords: bool = False) -> List[str]:
        if not text or not text.strip():
            return []
        if self._jieba:
            tokens = self._jieba.lcut(text)
        else:
            import re

            tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text)
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

    def add_stopwords(self, words: List[str]) -> None:
        for word in words:
            self._stopwords.add(word)

    @property
    def stopwords(self) -> Set[str]:
        return self._stopwords.copy()

    @property
    def has_jieba(self) -> bool:
        return self._jieba is not None


_tokenizer: Tokenizer | None = None


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


def tokenize(text: str, filter_stopwords: bool = False) -> List[str]:
    return get_tokenizer().tokenize(text, filter_stopwords=filter_stopwords)
