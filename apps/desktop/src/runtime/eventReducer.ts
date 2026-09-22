/**
 * 事件归约。按 (run_id, sequence) 幂等处理，可承受乱序、重复与断线重连补发。
 * 领域对象只来自结构化事件，不从自然语言解析。
 */
import type {
  Candidate,
  Challenge,
  Claim,
  Event as ProtocolEvent,
  EvidenceItem,
  InterruptPayload,
  LearningCheck,
} from "../types/protocol";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming: boolean;
};

export type RunStatus = "idle" | "running" | "interrupted" | "completed" | "failed" | "cancelled";

export type WorkspaceState = {
  seen: Record<string, true>;
  lastEventId: string | null;
  phase: string;
  runId: string | null;
  runStatus: RunStatus;
  messages: ChatMessage[];
  sources: EvidenceItem[];
  candidates: Candidate[];
  claims: Claim[];
  challenges: Challenge[];
  learningChecks: LearningCheck[];
  pendingInterrupt: (InterruptPayload & { predicted_eig?: number }) | null;
  degradations: string[];
  unknowns: string[];
  nextSteps: string[];
  error: { code: string; message: string } | null;
};

export const initialWorkspaceState: WorkspaceState = {
  seen: {},
  lastEventId: null,
  phase: "idle",
  runId: null,
  runStatus: "idle",
  messages: [],
  sources: [],
  candidates: [],
  claims: [],
  challenges: [],
  learningChecks: [],
  pendingInterrupt: null,
  degradations: [],
  unknowns: [],
  nextSteps: [],
  error: null,
};

function upsertById<T extends { id: string }>(list: T[], item: T): T[] {
  const index = list.findIndex((existing) => existing.id === item.id);
  if (index === -1) return [...list, item];
  const next = [...list];
  next[index] = { ...next[index], ...item };
  return next;
}

function upsertMessage(messages: ChatMessage[], message: ChatMessage): ChatMessage[] {
  const index = messages.findIndex((existing) => existing.id === message.id);
  if (index === -1) return [...messages, message];
  const next = [...messages];
  next[index] = message;
  return next;
}

/** 追加用户消息（本地乐观更新，不来自事件流）。 */
export function appendUserMessage(state: WorkspaceState, id: string, content: string): WorkspaceState {
  return {
    ...state,
    messages: upsertMessage(state.messages, { id, role: "user", content, streaming: false }),
    error: null,
  };
}

export function reduceEvent(state: WorkspaceState, event: ProtocolEvent): WorkspaceState {
  const key = `${event.run_id}#${event.sequence}`;
  if (state.seen[key]) return state; // 幂等：重复或重连补发的事件被忽略
  const base: WorkspaceState = {
    ...state,
    seen: { ...state.seen, [key]: true },
    lastEventId: event.event_id,
    runId: event.run_id,
  };
  const payload = (event.payload ?? {}) as Record<string, unknown>;

  switch (event.type) {
    case "run.started":
      return { ...base, runStatus: "running", error: null };
    case "phase.changed":
      return { ...base, phase: String(payload.phase ?? base.phase) };
    case "message.delta": {
      const id = String(payload.message_id);
      const previous = base.messages.find((m) => m.id === id);
      return {
        ...base,
        messages: upsertMessage(base.messages, {
          id,
          role: "assistant",
          content: `${previous?.content ?? ""}${String(payload.delta ?? "")}`,
          streaming: true,
        }),
      };
    }
    case "message.completed": {
      const id = String(payload.message_id);
      return {
        ...base,
        messages: upsertMessage(base.messages, {
          id,
          role: "assistant",
          content: String(payload.content ?? ""),
          streaming: false,
        }),
      };
    }
    case "source.added":
      return { ...base, sources: upsertById(base.sources, payload as unknown as EvidenceItem) };
    case "candidate.created":
    case "candidate.updated":
      return { ...base, candidates: upsertById(base.candidates, payload as unknown as Candidate) };
    case "challenge.created":
      return { ...base, challenges: upsertById(base.challenges, payload as unknown as Challenge) };
    case "claim.updated":
      return { ...base, claims: upsertById(base.claims, payload as unknown as Claim) };
    case "learning_check.created":
      return {
        ...base,
        learningChecks: upsertById(base.learningChecks, payload as unknown as LearningCheck),
      };
    case "interrupt.requested":
      return {
        ...base,
        runStatus: "interrupted",
        pendingInterrupt: payload as unknown as InterruptPayload & { predicted_eig?: number },
      };
    case "interrupt.resolved":
      return { ...base, pendingInterrupt: null };
    case "run.completed":
      return {
        ...base,
        runStatus: "completed",
        phase: "completed",
        unknowns: (payload.unknowns as string[]) ?? base.unknowns,
        nextSteps: (payload.next_steps as string[]) ?? base.nextSteps,
        degradations: (payload.degradations as string[]) ?? base.degradations,
        messages: base.messages.map((m) => ({ ...m, streaming: false })),
      };
    case "run.failed":
      return {
        ...base,
        runStatus: "failed",
        error: {
          code: String(payload.code ?? "internal_error"),
          message: String(payload.message ?? ""),
        },
        messages: base.messages.map((m) => ({ ...m, streaming: false })),
      };
    case "run.cancelled":
      return {
        ...base,
        runStatus: "cancelled",
        messages: base.messages.map((m) => ({ ...m, streaming: false })),
      };
    default:
      return base;
  }
}

export function reduceEvents(state: WorkspaceState, events: ProtocolEvent[]): WorkspaceState {
  return events.reduce(reduceEvent, state);
}

/** 会话冷启动：用 REST 快照初始化，再叠加实时事件。 */
export function hydrateFromSnapshot(snapshot: {
  phase: string;
  messages: { message_id: string; role: string; content: string }[];
  sources: EvidenceItem[];
  candidates: Candidate[];
  claims: Claim[];
  challenges: Challenge[];
  pending_interrupt: InterruptPayload | null;
  busy: boolean;
}): WorkspaceState {
  return {
    ...initialWorkspaceState,
    phase: snapshot.phase,
    messages: snapshot.messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({
        id: m.message_id,
        role: m.role as "user" | "assistant",
        content: m.content,
        streaming: false,
      })),
    sources: snapshot.sources,
    candidates: snapshot.candidates,
    claims: snapshot.claims,
    challenges: snapshot.challenges,
    pendingInterrupt: snapshot.pending_interrupt,
    runStatus: snapshot.pending_interrupt
      ? "interrupted"
      : snapshot.busy
        ? "running"
        : snapshot.phase === "completed"
          ? "completed"
          : "idle",
  };
}
