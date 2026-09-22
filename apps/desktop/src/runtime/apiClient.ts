/**
 * sidecar HTTP 客户端。baseUrl 与 token 由 Tauri 在启动时注入，开发模式回退到环境变量。
 * 前端不直接打开 SQLite，也不解析自然语言推断领域对象。
 */
import type {
  Candidate,
  Challenge,
  Claim,
  EvidenceItem,
  InterruptPayload,
  Message,
} from "../types/protocol";

export type SidecarConnection = { baseUrl: string; token: string };

export type SessionSummary = {
  session_id: string;
  title: string;
  topic: string;
  task_type: string;
  depth: "fast" | "deep";
  phase: string;
  created_at: string;
  updated_at: string;
};

export type SessionDetail = SessionSummary & {
  messages: (Message & { message_id: string; run_id: string | null })[];
  sources: EvidenceItem[];
  candidates: Candidate[];
  claims: Claim[];
  challenges: Challenge[];
  attachments: { attachment_id: string; filename: string; size: number }[];
  pending_interrupt: InterruptPayload | null;
  busy: boolean;
};

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string) {
    super(code);
  }
}

export class ApiClient {
  constructor(private connection: SidecarConnection) {}

  get baseUrl(): string {
    return this.connection.baseUrl;
  }

  get headers(): Record<string, string> {
    return { Authorization: `Bearer ${this.connection.token}` };
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.connection.baseUrl}${path}`, {
      ...init,
      headers: {
        ...this.headers,
        ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(init.headers ?? {}),
      },
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({ detail: "request_failed" }));
      throw new ApiError(response.status, String(detail.detail ?? "request_failed"));
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  health() {
    return this.request<{ status: string; model_configured: boolean; offline: boolean }>(
      "/health",
    );
  }

  listSessions() {
    return this.request<SessionSummary[]>("/v1/sessions");
  }

  createSession(title = "") {
    return this.request<SessionSummary>("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  }

  getSession(sessionId: string) {
    return this.request<SessionDetail>(`/v1/sessions/${sessionId}`);
  }

  deleteSession(sessionId: string) {
    return this.request<{ deleted: string }>(`/v1/sessions/${sessionId}`, { method: "DELETE" });
  }

  sendMessage(sessionId: string, content: string) {
    return this.request<{ run_id: string; message_id: string }>(
      `/v1/sessions/${sessionId}/messages`,
      { method: "POST", body: JSON.stringify({ content }) },
    );
  }

  resume(
    sessionId: string,
    body: {
      question_id?: string | null;
      learning_check_id?: string | null;
      option_id?: string | null;
      free_text?: string;
    },
  ) {
    return this.request<{ run_id: string }>(`/v1/sessions/${sessionId}/resume`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  cancel(sessionId: string) {
    return this.request<{ cancelled: boolean }>(`/v1/sessions/${sessionId}/cancel`, {
      method: "POST",
    });
  }

  candidateDecision(sessionId: string, candidateId: string, status: string, userNote = "") {
    return this.request<Candidate>(
      `/v1/sessions/${sessionId}/candidates/${candidateId}/decision`,
      { method: "POST", body: JSON.stringify({ status, user_note: userNote }) },
    );
  }

  challengeDecision(sessionId: string, challengeId: string, status: string) {
    return this.request<Challenge>(
      `/v1/sessions/${sessionId}/challenges/${challengeId}/decision`,
      { method: "POST", body: JSON.stringify({ status }) },
    );
  }

  /** 附件先上传，消息中只传 attachment ID。 */
  uploadAttachment(sessionId: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    return this.request<{ attachment_id: string; filename: string; chunks: number }>(
      `/v1/sessions/${sessionId}/attachments`,
      { method: "POST", body: form },
    );
  }

  exportSession(sessionId: string) {
    return this.request<{ files: string[] }>(`/v1/sessions/${sessionId}/export`, {
      method: "POST",
    });
  }

  getSettings() {
    return this.request<{
      model_configured: boolean;
      base_url: string;
      model: string;
      offline: boolean;
      data_dir: string;
    }>("/v1/settings");
  }

  saveApiKey(apiKey: string, baseUrl?: string, model?: string) {
    return this.request<{ model_configured: boolean }>("/v1/settings/api_key", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey, base_url: baseUrl, model }),
    });
  }

  eventsUrl(sessionId: string): string {
    return `${this.connection.baseUrl}/v1/sessions/${sessionId}/events`;
  }
}
