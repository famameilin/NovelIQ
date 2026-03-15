from __future__ import annotations

from pathlib import Path
from typing import List, Set

import jieba
from loguru import logger

from src.lexicons.loader import load_lexicon


def _default_stopwords_path() -> Path:
    return Path("data/lexicons/stopwords.txt")


PUNCTUATION_CHARS = set(
    '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~。！？；：""（）【】《》—…·～「」『』〈〉〔〕｛｝．，、；：？！／＼…‥•·′″'
)


def _is_punctuation(token: str) -> bool:
    if not token:
        return True
    if all(c in PUNCTUATION_CHARS or (ord(c) < 128 and not c.isalnum()) for c in token):
        return True
    return False


class TopicPreprocessor:
    def __init__(
        self,
        stopwords_path: Path | None = None,
        user_dict_path: Path | None = None,
        min_word_len: int = 2,
    ) -> None:
        self._stopwords_path = stopwords_path or _default_stopwords_path()
        self._user_dict_path = user_dict_path
        self._min_word_len = min_word_len
        self._stopwords: Set[str] = set()
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._load_stopwords()
        self._load_user_dict()
        self._initialized = True

    def _load_stopwords(self) -> None:
        try:
            words = load_lexicon("stopwords", self._stopwords_path.parent)
            self._stopwords = set(words)
            logger.debug("加载停用词: 数量={}, 路径={}", len(self._stopwords), self._stopwords_path)
        except FileNotFoundError:
            logger.warning("停用词文件不存在: {}, 使用空集合", self._stopwords_path)
            self._stopwords = set()

    def _load_user_dict(self) -> None:
        if self._user_dict_path and self._user_dict_path.exists():
            jieba.load_userdict(str(self._user_dict_path))
            logger.debug("加载jieba用户词典: {}", self._user_dict_path)

    def tokenize(self, text: str) -> List[str]:
        self._ensure_initialized()
        if not text or not text.strip():
            return []
        tokens = jieba.lcut(text)
        filtered = [
            token.strip()
            for token in tokens
            if token.strip()
            and len(token.strip()) >= self._min_word_len
            and token.strip() not in self._stopwords
            and not _is_punctuation(token.strip())
        ]
        return filtered

    def preprocess_documents(self, documents: List[str]) -> List[List[str]]:
        self._ensure_initialized()
        results: List[List[str]] = []
        for i, doc in enumerate(documents):
            tokens = self.tokenize(doc)
            results.append(tokens)
            if (i + 1) % 100 == 0:
                logger.debug("预处理进度: {}/{}", i + 1, len(documents))
        logger.info("预处理完成: 文档数={}", len(documents))
        return results

    def add_stopwords(self, words: List[str]) -> None:
        self._ensure_initialized()
        for word in words:
            self._stopwords.add(word)

    @property
    def stopwords(self) -> Set[str]:
        self._ensure_initialized()
        return self._stopwords.copy()
