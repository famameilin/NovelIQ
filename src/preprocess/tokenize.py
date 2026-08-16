from __future__ import annotations

from pathlib import Path

from loguru import logger


def _default_user_dict_path() -> Path:
    return Path("data/lexicons/jieba_user_dict.txt")


def _default_stopwords_path() -> Path:
    return Path("data/lexicons/stopwords.txt")


# 2026-08-16 情绪词重切分：删除"副词+单字情绪词（爽/慌）"与"爽/慌+得/到"的
# 融合词路由，使 jieba 切回 很|爽、爽|得，单字表词可被 token 对齐匹配命中。
# 融合词分两类：jieba 基础词典低频词（仅改用户词典文件无法移除，需运行时
# del_word）与 HMM 模型词（del_word 注册 force_split 阻断合并）。覆盖
# 副词×情绪字×{裸/了/的} 全矩阵；爱 类刻意不删（习惯性偏好漂移：最爱说/太爱装）。
_ADVERB_PREFIXES = ("很", "太", "好", "超", "巨", "特", "挺", "蛮", "更", "最", "极", "颇", "愈", "贼")
_EMOTION_SINGLE_CHARS = ("爽", "慌")
_EMOTION_FUSION_SPLITS = tuple(
    a + c + suffix
    for a in _ADVERB_PREFIXES
    for c in _EMOTION_SINGLE_CHARS
    for suffix in ("", "了", "的")
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
        # 情绪词重切分：删除融合词路由（基础词典里的低频融合词仅靠用户词典
        # 无法覆盖删除，需运行时移除；HMM 模型词由用户词典 freq=0 强制切分）
        for word in _EMOTION_FUSION_SPLITS:
            self._jieba.del_word(word)

    def tokenize(self, text: str, filter_stopwords: bool = False) -> list[str]:
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

    def add_stopwords(self, words: list[str]) -> None:
        for word in words:
            self._stopwords.add(word)

    @property
    def stopwords(self) -> set[str]:
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


def tokenize(text: str, filter_stopwords: bool = False) -> list[str]:
    return get_tokenizer().tokenize(text, filter_stopwords=filter_stopwords)
