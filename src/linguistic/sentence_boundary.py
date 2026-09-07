"""句级情绪边界（2026-09-07 句级监督：按书边界，用户定稿）

监督信号 = 标注 agent 逐章自选句的整句情绪标签（随 chapter_annotations 落库）；
边界 = 该书自己的句子现算的岭回归线性映射（backbone 句向量 → 情绪分值），
零新模型文件、numpy 亚秒级、确定性；无标签 run 无边界（上层保留词典/mNEG 口径）。

分值目标沿用 EMOTION_SCORE_MAPPING（strong_positive=2 … strong_negative=-2）；
p(负向) 由分值单调映射供分层（p≥0.8 强），跨书曲线口径不同不可比（用户已接受）。

纯函数，不依赖模型实例；测试可直接构造句向量矩阵。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.config.constants import EMOTION_SCORE_MAPPING

#: 岭正则强度：句向量已 L2 归一化、样本量小（每章 2-3 句），固定值保证数值稳定
_RIDGE_LAMBDA = 1.0
#: 强度分层阈值（方案：p≥0.8 强）
_STRONG_SCORE_THRESHOLD = 0.8
#: 句向量最大维度上限（防御异常模型输出，正常 LTP small=256）
_MAX_DIM = 4096


@dataclass(frozen=True)
class SentenceBoundary:
    """按书句级边界：权重向量与截距（负向分值方向）"""

    weights: tuple[float, ...]
    intercept: float
    sample_count: int

    def score(self, vector: np.ndarray) -> float:
        """单句分值：越高越正，越低越负（0 附近为中性带）"""
        return float(np.dot(vector, self.weights) + self.intercept)


def fit_sentence_boundary(
    vectors: np.ndarray,
    emotions: list[str],
) -> SentenceBoundary | None:
    """用全书自选句标签拟合线性边界（岭回归闭式解）

    vectors: (N, D) 句向量（建议 L2 归一化）；emotions: 长度 N 的情绪枚举。
    样本 <2 或全同分值（无边可学）返回 None——上层保留既有口径，不伪造边界。
    """
    if vectors.ndim != 2 or vectors.shape[0] != len(emotions) or vectors.shape[0] < 2:
        return None
    if vectors.shape[1] < 1 or vectors.shape[1] > _MAX_DIM:
        return None
    targets = np.array(
        [float(EMOTION_SCORE_MAPPING.get(emotion, 0)) for emotion in emotions],
        dtype=np.float64,
    )
    if float(np.ptp(targets)) == 0.0:
        return None
    x = vectors.astype(np.float64)
    # 中心化后解岭回归正规方程：(X^T X + λI) w = X^T y，截距=y_mean
    x_mean = x.mean(axis=0)
    y_mean = float(targets.mean())
    x_centered = x - x_mean
    y_centered = targets - y_mean
    d = x_centered.shape[1]
    gram = x_centered.T @ x_centered + _RIDGE_LAMBDA * np.eye(d)
    weights = np.linalg.solve(gram, x_centered.T @ y_centered)
    return SentenceBoundary(
        weights=tuple(float(w) for w in weights),
        intercept=y_mean - float(np.dot(x_mean, weights)),
        sample_count=len(emotions),
    )


def score_sentences(
    boundary: SentenceBoundary,
    vectors: np.ndarray,
) -> list[float | None]:
    """逐句打分：返回情绪分值列表（维度不匹配按 None 处理，不伪造）"""
    expected_dim = len(boundary.weights)
    scores: list[float | None] = []
    for vector in vectors:
        if vector.shape[0] != expected_dim:
            scores.append(None)
            continue
        score = boundary.score(vector)
        scores.append(score)
    return scores


def strong_negative_share(scores: list[float | None]) -> float | None:
    """强度分层占比（方案 p≥0.8 强的负向侧）：分值 ≤ -threshold 计强负"""
    valid = [score for score in scores if score is not None]
    if not valid:
        return None
    strong = sum(1 for score in valid if score <= -_STRONG_SCORE_THRESHOLD)
    return strong / len(valid)
