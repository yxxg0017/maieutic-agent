/**
 * SSE 订阅。使用 fetch 流式读取，以便携带 Authorization 头（EventSource 不支持）。
 * 断线后用 Last-Event-ID 续传，不重新运行图。
 */
import type { Event as ProtocolEvent } from "../types/protocol";
import type { ApiClient } from "./apiClient";

export type SseHandlers = {
  onEvent: (event: ProtocolEvent) => void;
  onConnectionChange?: (connected: boolean) => void;
  getLastEventId?: () => string | null;
};

type Frame = { id?: string; event?: string; data: string };

export function parseSseChunk(buffer: string): { frames: Frame[]; rest: string } {
  const frames: Frame[] = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  for (const block of parts) {
    const frame: Frame = { data: "" };
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("id:")) frame.id = line.slice(3).trim();
      else if (line.startsWith("event:")) frame.event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    frame.data = dataLines.join("\n");
    if (frame.data) frames.push(frame);
  }
  return { frames, rest };
}

export function subscribeEvents(
  api: ApiClient,
  sessionId: string,
  handlers: SseHandlers,
): () => void {
  const controller = new AbortController();
  let stopped = false;
  let attempt = 0;

  const run = async () => {
    while (!stopped) {
      try {
        const lastEventId = handlers.getLastEventId?.() ?? null;
        const response = await fetch(api.eventsUrl(sessionId), {
          headers: {
            ...api.headers,
            Accept: "text/event-stream",
            ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
          },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error(`sse_${response.status}`);
        handlers.onConnectionChange?.(true);
        attempt = 0;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!stopped) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { frames, rest } = parseSseChunk(buffer);
          buffer = rest;
          for (const frame of frames) {
            if (frame.event === "ping") continue;
            try {
              handlers.onEvent(JSON.parse(frame.data) as ProtocolEvent);
            } catch {
              // 非法帧直接忽略，避免污染状态
            }
          }
        }
      } catch (error) {
        if (stopped || controller.signal.aborted) return;
      }
      handlers.onConnectionChange?.(false);
      attempt += 1;
      const delay = Math.min(500 * 2 ** (attempt - 1), 8000);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  };

  void run();
  return () => {
    stopped = true;
    controller.abort();
  };
}
