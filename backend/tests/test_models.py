"""模型不变量：来源等级不被混淆，无来源内容不伪装成事实。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kel.models import Claim, EvidenceItem, EvidenceLink, HypothesisSet


def test_model_only_cannot_fake_a_locator():
    item = EvidenceItem(
        id="ev1",
        kind="model_knowledge",
        source_tier="model_only",
        locator="https://docs.python.org/3/",  # 伪装的引用
    )
    assert item.locator == "model:unverified"


def test_primary_keeps_its_locator_and_version():
    item = EvidenceItem(
        id="ev2",
        kind="official_documentation",
        source_tier="primary",
        locator="https://docs.python.org/3/reference/expressions.html",
        version="3.11",
    )
    assert item.locator.startswith("https://") and item.version == "3.11"


def test_unsourced_fact_is_downgraded_to_model_proposal():
    claim = Claim(id="c1", text="X 一定成立", type="fact")
    assert claim.type == "model_proposal"
    assert claim.source_tier == "model_only"


def test_sourced_fact_stays_a_fact():
    claim = Claim(
        id="c2",
        text="生成器在 next() 之间保留局部状态",
        type="fact",
        source_tier="primary",
        evidence_links=[EvidenceLink(evidence_id="ev2", asserted_by="source")],
    )
    assert claim.type == "fact" and claim.source_tier == "primary"


def test_hypothesis_probabilities_must_sum_to_one():
    with pytest.raises(ValidationError):
        HypothesisSet(
            id="hs1",
            latent_variable="v",
            hypotheses=[{"id": "h1", "text": "a", "p": 0.4}, {"id": "h2", "text": "b", "p": 0.4}],
        )


def test_hypothesis_set_needs_at_least_two_hypotheses():
    with pytest.raises(ValidationError):
        HypothesisSet(
            id="hs2", latent_variable="v", hypotheses=[{"id": "h1", "text": "a", "p": 1.0}]
        )
