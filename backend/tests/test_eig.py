"""EIG、熵与评分聚合的纯代码测试。"""

from __future__ import annotations

import numpy as np
import pytest

from kel.eig import (
    answer_marginal,
    apply_noise_floor,
    entropy,
    expected_information_gain,
    posterior,
    rank_questions,
    weighted_score,
)


def test_entropy_uniform_two_is_one_bit():
    assert entropy(np.array([0.5, 0.5])) == pytest.approx(1.0)


def test_entropy_certain_is_zero():
    assert entropy(np.array([1.0, 0.0])) == pytest.approx(0.0)


def test_noise_floor_keeps_rows_normalized():
    matrix = apply_noise_floor(np.array([[1.0, 0.0], [0.0, 1.0]]))
    assert matrix.sum(axis=1) == pytest.approx([1.0, 1.0])
    assert matrix.min() > 0


def test_perfectly_diagnostic_question_has_max_eig():
    prior = np.array([0.5, 0.5])
    perfect = np.array([[1.0, 0.0], [0.0, 1.0]])
    useless = np.array([[0.5, 0.5], [0.5, 0.5]])
    assert expected_information_gain(prior, perfect) > expected_information_gain(
        prior, useless
    )
    assert expected_information_gain(prior, useless) == pytest.approx(0.0, abs=1e-9)


def test_posterior_and_marginal_are_consistent():
    prior = np.array([0.6, 0.4])
    likelihood = np.array([[0.8, 0.2], [0.3, 0.7]])
    marginal = answer_marginal(prior, likelihood)
    assert marginal.sum() == pytest.approx(1.0)
    post = posterior(prior, likelihood, 0)
    assert post.sum() == pytest.approx(1.0)
    assert post[0] > prior[0]  # 答案 0 更支持 h1


def test_rank_questions_puts_degraded_last():
    prior = np.array([0.5, 0.5])
    ranked = rank_questions(
        prior,
        {
            "q_good": np.array([[0.9, 0.1], [0.1, 0.9]]),
            "q_degraded": np.array([[0.95, 0.05], [0.05, 0.95]]),
        },
        degraded={"q_degraded"},
    )
    assert [r.question_id for r in ranked] == ["q_good", "q_degraded"]


def test_weighted_score_is_deterministic_and_ignores_missing():
    scores = {"relevance": 1.0, "evidence": 0.0}
    weights = {"relevance": 0.5, "evidence": 0.25, "novelty": 0.25}
    assert weighted_score(scores, weights) == pytest.approx(0.5)
    assert weighted_score(scores, {}) == 0.0
