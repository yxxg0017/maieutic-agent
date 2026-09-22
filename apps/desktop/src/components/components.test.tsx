import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Candidate, Challenge, EvidenceItem } from "../types/protocol";
import { CandidateComparison } from "./candidates/CandidateComparison";
import { ChallengeCard } from "./challenges/ChallengeCard";
import { InterruptForm } from "./conversation/InterruptForm";
import { SourceList } from "./sources/SourceCard";

function candidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    id: "c1",
    text: "把生成器理解为状态机",
    mechanism: "帧对象保存局部状态",
    differentiator: "强调执行状态",
    evidence_ids: [],
    assumptions: ["无可定位来源，基于模型已有知识（未核验）"],
    failure_modes: ["close() 后行为不同"],
    verification: "打印副作用顺序",
    scores: { relevance: 0.9, aggregate: 0.8 },
    status: "generated",
    user_note: "",
    ...overrides,
  } as Candidate;
}

describe("SourceList", () => {
  it("distinguishes source tiers and marks unverified model knowledge", () => {
    const sources: EvidenceItem[] = [
      {
        id: "ev1",
        kind: "official_documentation",
        title: "Python 官方文档",
        context: "yield 表达式",
        observed_at_time: [],
        later_learned: [],
        current_interpretation: [],
        source_spans: [],
        source_tier: "primary",
        locator: "https://docs.python.org/3/reference/expressions.html",
        version: "3.11",
        status: "retrieved",
      } as EvidenceItem,
      {
        id: "ev2",
        kind: "model_knowledge",
        title: "模型记忆",
        context: "",
        observed_at_time: [],
        later_learned: [],
        current_interpretation: [],
        source_spans: [],
        source_tier: "model_only",
        locator: "model:unverified",
        version: null,
        status: "model_proposal",
      } as EvidenceItem,
    ];
    render(<SourceList sources={sources} claims={[]} />);
    expect(screen.getByText("一手来源")).toBeInTheDocument();
    expect(screen.getByText("模型已有知识，未核验")).toBeInTheDocument();
  });

  it("explains the empty state instead of implying sources exist", () => {
    render(<SourceList sources={[]} claims={[]} />);
    expect(screen.getByText(/未核验/)).toBeInTheDocument();
  });
});

describe("CandidateComparison", () => {
  it("shows every fixed dimension and reports the user decision", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    render(
      <CandidateComparison
        candidates={[candidate(), candidate({ id: "c2", text: "惰性流水线" })]}
        onDecide={onDecide}
      />,
    );
    for (const label of ["核心想法", "关键差异", "机制", "依据", "假设", "失败模式", "最低成本验证", "各维度评分"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    await userEvent.click(screen.getAllByRole("button", { name: "淘汰" })[0]);
    expect(onDecide).toHaveBeenCalledWith("c1", "rejected", "");
  });

  it("does not collapse candidates into a single aggregate score", () => {
    render(<CandidateComparison candidates={[candidate()]} onDecide={vi.fn()} />);
    expect(screen.getByText("relevance: 0.90")).toBeInTheDocument();
    expect(screen.queryByText(/aggregate/)).not.toBeInTheDocument();
  });
});

describe("ChallengeCard", () => {
  it("separates model proposals from user rulings", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    const challenge: Challenge = {
      id: "ch1",
      claim_id: null,
      candidate_id: "c1",
      text: "被 close() 之后是否仍成立？",
      source: "model_generated_probe",
      status: "untested",
      confirmed_by_turn_id: null,
    } as Challenge;
    render(<ChallengeCard challenge={challenge} onDecide={onDecide} />);
    expect(screen.getByText("模型提议，未裁决")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "仅在某条件成立" }));
    expect(onDecide).toHaveBeenCalledWith("ch1", "conditional");
  });
});

describe("InterruptForm", () => {
  it("submits the selected option through resume", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <InterruptForm
        pending={{
          kind: "question",
          question_id: "q1",
          learning_check_id: null,
          text: "你能预测求值时机吗？",
          options: [
            { id: "can_write", label: "能写但不能预测" },
            { id: "uncertain", label: "不确定" },
          ],
          free_text_allowed: true,
        }}
        onSubmit={onSubmit}
      />,
    );
    await userEvent.click(screen.getByLabelText("能写但不能预测"));
    await userEvent.click(screen.getByRole("button", { name: "提交" }));
    expect(onSubmit).toHaveBeenCalledWith({ optionId: "can_write", freeText: "" });
  });

  it("renders nothing when there is no pending interrupt", () => {
    const { container } = render(<InterruptForm pending={null} onSubmit={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
