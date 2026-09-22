"""EIG、熵与信念更新。全部为纯计算，不调用模型。

规格来源：`知识激发智能体_实现规格.md` 第 5 节。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NOISE_FLOOR = 0.02


def entropy(prior: np.ndarray) -> float:
    """以 bit 为单位的香农熵。零概率项按 0 处理。"""
    p = np.asarray(prior, dtype=float)
    nz = p[p > 0]
    return float(-np.sum(nz * np.log2(nz)))


def normalize(values: np.ndarray) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    total = v.sum()
    if total <= 0:
        return np.full_like(v, 1.0 / len(v))
    return v / total


def apply_noise_floor(matrix: np.ndarray, floor: float = NOISE_FLOOR) -> np.ndarray:
    """对 likelihood 施加噪声下限后按行归一化。

    避免单一答案把后验压成 0/1，从而让 EIG 过度自信。
    """
    m = np.clip(np.asarray(matrix, dtype=float), floor, None)
    return m / m.sum(axis=1, keepdims=True)


def answer_marginal(prior: np.ndarray, likelihood: np.ndarray) -> np.ndarray:
    """P(a|q) = sum_i p_i P(a|h_i,q)"""
    return normalize(np.asarray(prior, dtype=float) @ np.asarray(likelihood, dtype=float))


def posterior(prior: np.ndarray, likelihood: np.ndarray, answer_index: int) -> np.ndarray:
    """P(h_i|a,q)"""
    p = np.asarray(prior, dtype=float)
    column = np.asarray(likelihood, dtype=float)[:, answer_index]
    return normalize(p * column)


def expected_information_gain(prior: np.ndarray, likelihood: np.ndarray) -> float:
    """EIG(q) = H(p) - sum_a P(a|q) H(p|a,q)"""
    p = np.asarray(prior, dtype=float)
    lk = np.asarray(likelihood, dtype=float)
    marginal = answer_marginal(p, lk)
    expected = 0.0
    for a in range(lk.shape[1]):
        if marginal[a] <= 0:
            continue
        expected += marginal[a] * entropy(posterior(p, lk, a))
    return float(entropy(p) - expected)


@dataclass(frozen=True)
class RankedQuestion:
    question_id: str
    eig: float
    degraded: bool


def rank_questions(
    prior: np.ndarray,
    likelihoods: dict[str, np.ndarray],
    degraded: set[str] | None = None,
) -> list[RankedQuestion]:
    """按 EIG 降序排序。`uniform_fallback` 的问题排在最后。

    排序稳定且与输入顺序无关，便于回放。
    """
    degraded = degraded or set()
    ranked = [
        RankedQuestion(
            question_id=qid,
            eig=expected_information_gain(prior, apply_noise_floor(matrix)),
            degraded=qid in degraded,
        )
        for qid, matrix in likelihoods.items()
    ]
    ranked.sort(key=lambda r: (r.degraded, -r.eig, r.question_id))
    return ranked


def weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    """确定性加权聚合。缺失维度按 0 计，权重和为 0 时返回 0。"""
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0.0
    acc = sum(scores.get(name, 0.0) * weight for name, weight in weights.items())
    return round(acc / total_weight, 6)
