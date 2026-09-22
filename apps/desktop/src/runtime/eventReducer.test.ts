import { describe, expect, it } from "vitest";

import type { Event as ProtocolEvent } from "../types/protocol";
import {
  hydrateFromSnapshot,
  initialWorkspaceState,
  reduceEvent,
  reduceEvents,
} from "./eventReducer";

function event(
  type: string,
  sequence: number,
  payload: Record<string, unknown> = {},
  runId = "run_1",
): ProtocolEvent {
  return {
    schema_version: "1",
    event_id: `evt_${runId}_${sequence}`,
    session_id: "sess_1",
    run_id: runId,
    sequence,
    type,
    timestamp: "2026-09-22T00:00:00.000Z",
    payload,
  } as unknown as ProtocolEvent;
}

describe("reduceEvent", () => {
  it("streams deltas then replaces with the completed message", () => {
    const state = reduceEvents(initialWorkspaceState, [
      event("run.started", 1),
      event("message.delta", 2, { message_id: "m1", delta: "生成器" }),
      event("message.delta", 3, { message_id: "m1", delta: "是状态机" }),
    ]);
    expect(state.messages[0]).toMatchObject({
      id: "m1",
      content: "生成器是状态机",
      streaming: true,
    });

    const completed = reduceEvent(
      state,
      event("message.completed", 4, { message_id: "m1", content: "生成器是状态机。" }),
    );
    expect(completed.messages).toHaveLength(1);
    expect(completed.messages[0]).toMatchObject({ content: "生成器是状态机。", streaming: false });
  });

  it("ignores duplicated (run_id, sequence) pairs", () => {
    const delta = event("message.delta", 2, { message_id: "m1", delta: "A" });
    let state = reduceEvent(initialWorkspaceState, delta);
    state = reduceEvent(state, delta);
    state = reduceEvent(state, { ...delta, event_id: "evt_other" });
    expect(state.messages[0].content).toBe("A");
  });

  it("applies the same sequence number from a different run", () => {
    let state = reduceEvent(
      initialWorkspaceState,
      event("message.delta", 2, { message_id: "m1", delta: "A" }),
    );
    state = reduceEvent(
      state,
      event("message.delta", 2, { message_id: "m2", delta: "B" }, "run_2"),
    );
    expect(state.messages.map((m) => m.id)).toEqual(["m1", "m2"]);
  });

  it("upserts candidates without duplicating them on replay", () => {
    const created = event("candidate.created", 2, { id: "c1", text: "A", status: "generated" });
    const updated = event("candidate.updated", 3, { id: "c1", status: "kept" });
    const state = reduceEvents(initialWorkspaceState, [created, updated, created, updated]);
    expect(state.candidates).toHaveLength(1);
    expect(state.candidates[0]).toMatchObject({ id: "c1", text: "A", status: "kept" });
  });

  it("tracks pending interrupt and clears it when resolved", () => {
    let state = reduceEvent(
      initialWorkspaceState,
      event("interrupt.requested", 2, {
        kind: "question",
        question_id: "q1",
        text: "你卡在哪里？",
        options: [{ id: "a", label: "A" }],
        free_text_allowed: true,
        predicted_eig: 0.42,
      }),
    );
    expect(state.runStatus).toBe("interrupted");
    expect(state.pendingInterrupt?.question_id).toBe("q1");

    state = reduceEvent(state, event("interrupt.resolved", 3, { question_id: "q1" }));
    expect(state.pendingInterrupt).toBeNull();
  });

  it("records degradations and stops streaming flags on completion", () => {
    let state = reduceEvent(
      initialWorkspaceState,
      event("message.delta", 1, { message_id: "m1", delta: "x" }),
    );
    state = reduceEvent(
      state,
      event("run.completed", 2, {
        stop_reason: "completed",
        unknowns: ["未核验的实现细节"],
        next_steps: ["写一个最小实验"],
        degradations: ["检索失败，降级为模型已有知识"],
      }),
    );
    expect(state.runStatus).toBe("completed");
    expect(state.messages.every((m) => !m.streaming)).toBe(true);
    expect(state.degradations).toEqual(["检索失败，降级为模型已有知识"]);
    expect(state.unknowns).toHaveLength(1);
  });

  it("surfaces failures as user readable errors", () => {
    const state = reduceEvent(
      initialWorkspaceState,
      event("run.failed", 1, { code: "model_unreachable", message: "无法连接模型服务" }),
    );
    expect(state.runStatus).toBe("failed");
    expect(state.error).toEqual({ code: "model_unreachable", message: "无法连接模型服务" });
  });

  it("keeps last_event_id so reconnects can resume", () => {
    const state = reduceEvents(initialWorkspaceState, [
      event("run.started", 1),
      event("phase.changed", 2, { phase: "diverge" }),
    ]);
    expect(state.lastEventId).toBe("evt_run_1_2");
    expect(state.phase).toBe("diverge");
  });
});

describe("hydrateFromSnapshot", () => {
  it("restores interrupted state after restart", () => {
    const state = hydrateFromSnapshot({
      phase: "clarify",
      messages: [
        { message_id: "m1", role: "user", content: "问题" },
        { message_id: "m2", role: "system", content: "忽略" },
      ],
      sources: [],
      candidates: [],
      claims: [],
      challenges: [],
      pending_interrupt: {
        kind: "question",
        question_id: "q1",
        learning_check_id: null,
        text: "?",
        options: [],
        free_text_allowed: true,
      },
      busy: false,
    });
    expect(state.messages).toHaveLength(1);
    expect(state.runStatus).toBe("interrupted");
    expect(state.pendingInterrupt?.question_id).toBe("q1");
  });
});
