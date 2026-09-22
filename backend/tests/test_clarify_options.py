"""clarify 节点的选项解析：拒绝占位符标签。"""

from __future__ import annotations

from kel.contracts import ClarifyOut
from kel.nodes.clarify import _build_questions, _option_label


def _out(options: list[dict]) -> ClarifyOut:
    return ClarifyOut(
        latent_variable="v",
        hypotheses=[{"id": "h1", "text": "a", "p": 0.5}, {"id": "h2", "text": "b", "p": 0.5}],
        questions=[{"id": "q1", "text": "你的进程关系是哪种？", "options": options}],
    )


def test_label_accepts_alternative_keys():
    assert _option_label({"id": "o1", "text": "父子进程"}) == "父子进程"
    assert _option_label({"id": "o1", "name": "同一进程"}) == "同一进程"
    assert _option_label({"id": "o1", "label": "跨机器"}) == "跨机器"


def test_placeholder_label_is_invalid():
    assert _option_label({"id": "o1", "label": "o1"}) == ""
    assert _option_label({"id": "o1"}) == ""


def test_question_with_placeholder_labels_is_dropped():
    """模型只回 o1/o2 时，问题对用户没有意义，不应进入 interrupt。"""
    questions = _build_questions(_out([{"id": "o1"}, {"id": "o2"}]))
    assert questions == []


def test_readable_options_get_fixed_tail_options():
    questions = _build_questions(
        _out([{"id": "o1", "text": "父子进程"}, {"id": "o2", "text": "两个独立进程"}])
    )
    assert len(questions) == 1
    assert [o.id for o in questions[0].options] == ["o1", "o2", "other", "uncertain"]
    assert [o.label for o in questions[0].options][:2] == ["父子进程", "两个独立进程"]


def test_model_supplied_other_is_ignored():
    questions = _build_questions(
        _out(
            [
                {"id": "o1", "text": "父子进程"},
                {"id": "o2", "text": "独立进程"},
                {"id": "other", "text": "其他情况"},
            ]
        )
    )
    assert [o.id for o in questions[0].options].count("other") == 1
