"""渲染与 CLI 解析。渲染用固定宽度转成纯文本后断言，不依赖终端。"""

from __future__ import annotations

from kel.cli import DECISION_WORDS, RULING_WORDS, parse_index_command, parse_interrupt_answer
from kel.render import (
    banner,
    candidate_panel,
    challenges_table,
    claims_group,
    render_to_text,
    sessions_table,
    sources_table,
)


def text(renderable) -> str:
    return render_to_text(renderable, width=90)


def test_candidate_panel_shows_all_dimensions_without_aggregate():
    out = text(
        candidate_panel(
            0,
            {
                "text": "把生成器理解为状态机",
                "differentiator": "强调执行状态",
                "mechanism": "帧对象保存局部状态",
                "assumptions": ["无可定位来源"],
                "failure_modes": ["close() 后行为不同"],
                "verification": "打印副作用顺序",
                "scores": {"relevance": 0.9, "aggregate": 0.81},
                "status": "kept",
            },
        )
    )
    for expected in ("关键差异", "机制", "假设", "失败模式", "最低成本验证", "保留"):
        assert expected in out
    assert "relevance 0.90" in out
    assert "aggregate" not in out  # 不用单一总分掩盖差异


def test_source_tiers_are_visually_distinct():
    out = text(
        sources_table(
            [
                {"source_tier": "primary", "title": "官方文档", "locator": "https://x"},
                {"source_tier": "model_only", "title": "模型记忆", "locator": "model:unverified"},
            ]
        )
    )
    assert "[一手]" in out and "[未核验]" in out


def test_challenge_status_distinguishes_model_and_user():
    rows = [
        {"text": "探针一", "status": "untested"},
        {"text": "探针二", "status": "conditional"},
    ]
    out = text(challenges_table(rows))
    assert "模型提议，未裁决" in out
    assert "仅在某条件成立" in out


def test_claims_show_tier_boundaries_and_evidence():
    out = text(
        claims_group(
            [
                {
                    "text": "结论一",
                    "source_tier": "primary",
                    "boundaries": [{"text": "边界一", "status": "untested"}],
                    "evidence_links": [{"evidence_id": "ev_1", "relation": "supports"}],
                }
            ]
        )
    )
    assert "[一手]" in out and "边界一" in out and "ev_1" in out


def test_banner_warns_when_key_missing():
    out = text(banner("deepseek-chat", "https://api.deepseek.com/v1", "/tmp/d", False, False))
    assert "未配置" in out and "deepseek-chat" in out
    assert "/online on" in out


def test_sessions_table_marks_active():
    out = text(
        sessions_table(
            [
                {"session_id": "sess_1", "depth": "deep", "phase": "completed", "title": "甲"},
                {"session_id": "sess_2", "depth": "fast", "phase": "task_frame", "title": "乙"},
            ],
            active="sess_2",
        )
    )
    lines = [line for line in out.splitlines() if "sess_" in line]
    assert lines[0].strip().startswith("sess_1")
    assert lines[1].strip().startswith("*")


def test_interrupt_answer_accepts_number_id_and_free_text():
    payload = {"options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
    assert parse_interrupt_answer("2", payload)["option_id"] == "b"
    assert parse_interrupt_answer(" a ", payload)["option_id"] == "a"
    assert parse_interrupt_answer("", payload)["option_id"] == "uncertain"
    free = parse_interrupt_answer("其实是父子进程", payload)
    assert free["option_id"] is None and free["free_text"] == "其实是父子进程"
    assert parse_interrupt_answer("9", payload)["free_text"] == "9"  # 越界不当作选项


def test_index_command_parsing():
    assert parse_index_command("/decide 2 淘汰", DECISION_WORDS) == (1, "rejected")
    assert parse_index_command("/rule 1 条件", RULING_WORDS) == (0, "conditional")
    assert parse_index_command("/decide 2", DECISION_WORDS) is None
    assert parse_index_command("/decide x 保留", DECISION_WORDS) is None
    assert parse_index_command("/decide 2 乱写", DECISION_WORDS) is None
