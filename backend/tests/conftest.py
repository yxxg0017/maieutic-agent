"""共享 fixture。所有测试离线运行，不调用真实模型服务。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kel.adapters import ScriptedAdapter
from kel.api import create_app
from kel.config import Settings
from kel.security import new_session_token
from kel.store import Store

FAST_FRAME = {
    "topic": "解释 Python 生成器的惰性求值",
    "task_type": "learn",
    "depth": "fast",
    "desired_output": "一段可验证的解释",
    "value_criteria": [],
    "missing_information": [],
    "need_fresh_sources": False,
}

DEEP_FRAME = {**FAST_FRAME, "depth": "deep", "task_type": "compare"}

CLARIFY_OUT = {
    "latent_variable": "用户当前的真实卡点",
    "hypotheses": [
        {"id": "h1", "text": "不会写生成器", "p": 0.5},
        {"id": "h2", "text": "无法预测惰性行为", "p": 0.5},
    ],
    "questions": [
        {
            "id": "q1",
            "text": "你能预测 next() 的求值时机吗？",
            "options": [
                {"id": "can_write", "label": "能写但不能预测"},
                {"id": "cannot_write", "label": "写不出来"},
            ],
        }
    ],
}

LIKELIHOOD_OUT = {
    "rows": [
        {
            "question_id": "q1",
            "hypothesis_id": "h1",
            "probabilities": {
                "can_write": 0.1, "cannot_write": 0.8, "other": 0.05, "uncertain": 0.05,
            },
        },
        {
            "question_id": "q1",
            "hypothesis_id": "h2",
            "probabilities": {
                "can_write": 0.8, "cannot_write": 0.1, "other": 0.05, "uncertain": 0.05,
            },
        },
    ]
}

DIVERGE_OUT = {
    "candidates": [
        {
            "text": "把生成器理解为暂停/恢复的状态机",
            "mechanism": "帧对象保存局部状态直到下一次 next()",
            "differentiator": "强调执行状态而非集合",
            "evidence_ids": [],
            "assumptions": [],
            "verification": "在 next() 前后打印副作用",
        },
        {
            "text": "把生成器理解为惰性流水线",
            "mechanism": "每次消费驱动上游产生一个元素",
            "differentiator": "强调数据流与内存占用",
            "evidence_ids": [],
            "assumptions": [],
            "verification": "对比 list 与 generator 的内存",
        },
    ]
}

CHALLENGE_OUT = {
    "items": [
        {
            "candidate_index": 0,
            "failure_modes": ["含 try/finally 的生成器提前关闭时行为不同"],
            "boundary_probe": "若生成器被 close()，状态机模型是否仍成立？",
            "scores": {"relevance": 0.9, "specificity": 0.8, "evidence": 0.3},
        },
        {
            "candidate_index": 1,
            "failure_modes": ["有缓冲的迭代器会打破逐元素直觉"],
            "boundary_probe": "存在预读缓冲时惰性流水线模型是否成立？",
            "scores": {"relevance": 0.8, "specificity": 0.6, "evidence": 0.4},
        },
    ]
}

SYNTHESIZE_OUT = {
    "answer_markdown": "## 结论\n生成器是可暂停的执行状态机。",
    "kept_candidate_indexes": [0],
    "rejected_candidate_indexes": [1],
    "claims": [
        {
            "text": "生成器在 next() 之间保留局部状态",
            "type": "inference",
            "evidence_ids": [],
            "boundaries": ["close() 之后不再恢复"],
            "confidence": 0.7,
        }
    ],
    "unknowns": ["CPython 之外的实现细节未核验"],
    "next_steps": ["写一个带 finally 的生成器验证关闭行为"],
}

LEARN_CHECK_OUT = {
    "kind": "predict",
    "prompt": "预测下面这段生成器代码的打印顺序",
    "expected_signals": ["指出副作用发生在第一次 next() 时"],
}


def scripted(extra: dict | None = None) -> ScriptedAdapter:
    responses = {
        "task_frame": FAST_FRAME,
        "clarify": CLARIFY_OUT,
        "likelihood": LIKELIHOOD_OUT,
        "diverge": DIVERGE_OUT,
        "challenge": CHALLENGE_OUT,
        "synthesize": SYNTHESIZE_OUT,
        "learn_check": LEARN_CHECK_OUT,
    }
    responses.update(extra or {})
    return ScriptedAdapter(responses, stream_text="生成器按需求值。每次 next() 推进一步。")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", session_token=new_session_token())


@pytest.fixture
def store(settings: Settings) -> Store:
    return Store(settings.db_path)


@pytest.fixture
def adapter() -> ScriptedAdapter:
    return scripted()


@pytest.fixture
def client(settings: Settings, store: Store, adapter: ScriptedAdapter):
    app = create_app(settings, store, model_factory=lambda: adapter)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.headers.update({"Authorization": f"Bearer {settings.session_token}"})
        yield test_client
