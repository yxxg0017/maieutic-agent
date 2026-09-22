/**
 * 会话运行时：SSE 事件 → reducer → UI；用户操作 → REST。
 * interrupt 只能通过 /resume 提交，不伪装成普通聊天消息。
 */
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import type { Event as ProtocolEvent } from "../types/protocol";
import type { ApiClient, SessionDetail } from "./apiClient";
import {
  appendUserMessage,
  hydrateFromSnapshot,
  initialWorkspaceState,
  reduceEvent,
  type WorkspaceState,
} from "./eventReducer";
import { subscribeEvents } from "./sseClient";

type Action =
  | { type: "event"; event: ProtocolEvent }
  | { type: "hydrate"; snapshot: SessionDetail }
  | { type: "user_message"; id: string; content: string }
  | { type: "connection"; connected: boolean }
  | { type: "reset" }
  | { type: "error"; code: string; message: string };

export type SessionRuntimeState = WorkspaceState & { connected: boolean };

const initialState: SessionRuntimeState = { ...initialWorkspaceState, connected: false };

function reducer(state: SessionRuntimeState, action: Action): SessionRuntimeState {
  switch (action.type) {
    case "event":
      return { ...reduceEvent(state, action.event), connected: state.connected };
    case "hydrate":
      return { ...hydrateFromSnapshot(action.snapshot), connected: state.connected };
    case "user_message":
      return { ...appendUserMessage(state, action.id, action.content), connected: state.connected };
    case "connection":
      return { ...state, connected: action.connected };
    case "error":
      return { ...state, error: { code: action.code, message: action.message } };
    case "reset":
      return initialState;
    default:
      return state;
  }
}

export function useSessionRuntime(api: ApiClient, sessionId: string | null) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const lastEventId = useRef<string | null>(null);
  lastEventId.current = state.lastEventId;

  useEffect(() => {
    dispatch({ type: "reset" });
    if (!sessionId) return;
    let cancelled = false;
    void api
      .getSession(sessionId)
      .then((snapshot) => {
        if (!cancelled) dispatch({ type: "hydrate", snapshot });
      })
      .catch((error: Error) =>
        dispatch({ type: "error", code: "session_load_failed", message: error.message }),
      );
    const unsubscribe = subscribeEvents(api, sessionId, {
      onEvent: (event) => dispatch({ type: "event", event }),
      onConnectionChange: (connected) => dispatch({ type: "connection", connected }),
      getLastEventId: () => lastEventId.current,
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [api, sessionId]);

  const send = useCallback(
    async (content: string) => {
      if (!sessionId) return;
      const localId = `local_${Date.now()}`;
      dispatch({ type: "user_message", id: localId, content });
      try {
        await api.sendMessage(sessionId, content);
      } catch (error) {
        const code = error instanceof Error ? error.message : "send_failed";
        dispatch({ type: "error", code, message: "消息未发送" });
      }
    },
    [api, sessionId],
  );

  const resume = useCallback(
    async (body: { optionId?: string | null; freeText?: string }) => {
      if (!sessionId || !state.pendingInterrupt) return;
      const pending = state.pendingInterrupt;
      try {
        await api.resume(sessionId, {
          question_id: pending.question_id ?? null,
          learning_check_id: pending.learning_check_id ?? null,
          option_id: body.optionId ?? null,
          free_text: body.freeText ?? "",
        });
      } catch (error) {
        const code = error instanceof Error ? error.message : "resume_failed";
        dispatch({ type: "error", code, message: "回答未提交，可能已过期" });
      }
    },
    [api, sessionId, state.pendingInterrupt],
  );

  const cancel = useCallback(async () => {
    if (sessionId) await api.cancel(sessionId);
  }, [api, sessionId]);

  const decideCandidate = useCallback(
    async (candidateId: string, status: string, note = "") => {
      if (!sessionId) return;
      const updated = await api.candidateDecision(sessionId, candidateId, status, note);
      dispatch({
        type: "event",
        event: {
          schema_version: "1",
          event_id: `local_${candidateId}_${status}`,
          session_id: sessionId,
          run_id: "local",
          sequence: Date.now(),
          type: "candidate.updated",
          timestamp: new Date().toISOString(),
          payload: updated as unknown as Record<string, never>,
        } as ProtocolEvent,
      });
    },
    [api, sessionId],
  );

  const decideChallenge = useCallback(
    async (challengeId: string, status: string) => {
      if (!sessionId) return;
      const updated = await api.challengeDecision(sessionId, challengeId, status);
      dispatch({
        type: "event",
        event: {
          schema_version: "1",
          event_id: `local_${challengeId}_${status}`,
          session_id: sessionId,
          run_id: "local",
          sequence: Date.now() + 1,
          type: "challenge.created",
          timestamp: new Date().toISOString(),
          payload: updated as unknown as Record<string, never>,
        } as ProtocolEvent,
      });
    },
    [api, sessionId],
  );

  return useMemo(
    () => ({ state, send, resume, cancel, decideCandidate, decideChallenge }),
    [state, send, resume, cancel, decideCandidate, decideChallenge],
  );
}
