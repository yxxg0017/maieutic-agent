/** 会话列表与新建/删除/导出。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiClient } from "../runtime/apiClient";

export function SessionList(props: {
  api: ApiClient;
  activeSessionId: string | null;
  onSelect: (sessionId: string | null) => void;
}) {
  const { api, activeSessionId, onSelect } = props;
  const queryClient = useQueryClient();
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api.listSessions(),
    refetchInterval: 5000,
  });

  const create = useMutation({
    mutationFn: () => api.createSession(),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      onSelect(session.session_id);
    },
  });

  const remove = useMutation({
    mutationFn: (sessionId: string) => api.deleteSession(sessionId),
    onSuccess: (_, sessionId) => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      if (sessionId === activeSessionId) onSelect(null);
    },
  });

  return (
    <nav className="session-list">
      <button
        type="button"
        className="button primary block"
        onClick={() => create.mutate()}
        disabled={create.isPending}
      >
        新建会话
      </button>
      {sessions.isError ? <p className="error-note">无法读取会话列表</p> : null}
      <ul>
        {(sessions.data ?? []).map((session) => (
          <li key={session.session_id} aria-current={session.session_id === activeSessionId}>
            <button type="button" className="session-item" onClick={() => onSelect(session.session_id)}>
              <span className="session-title">{session.title || session.topic || "未命名会话"}</span>
              <span className="session-meta">
                {session.depth === "deep" ? "深度" : "快速"} · {session.phase}
              </span>
            </button>
            <button
              type="button"
              className="button small danger"
              aria-label="删除会话"
              onClick={() => {
                if (window.confirm("删除该会话及其本地数据？此操作不可撤销。")) {
                  remove.mutate(session.session_id);
                }
              }}
            >
              删除
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
