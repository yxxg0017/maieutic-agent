import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { ApiClient, type SidecarConnection } from "./runtime/apiClient";
import { resolveConnection } from "./runtime/connection";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

/** sidecar 不可用时提供重试与安全退出，不让应用崩溃。 */
function Bootstrap() {
  const [connection, setConnection] = useState<SidecarConnection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    void resolveConnection()
      .then(async (resolved) => {
        const api = new ApiClient(resolved);
        await api.health();
        if (!cancelled) setConnection(resolved);
      })
      .catch((cause: Error) => {
        if (!cancelled) setError(cause.message);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (error) {
    return (
      <div className="bootstrap-error" role="alert">
        <h2>本地服务未启动</h2>
        <p>错误：{error}</p>
        <div className="bootstrap-actions">
          <button type="button" className="button primary" onClick={() => setAttempt((n) => n + 1)}>
            重试
          </button>
          <button
            type="button"
            className="button"
            onClick={() => {
              void import("@tauri-apps/api/core")
                .then((m) => m.invoke("reveal_log_dir"))
                .catch(() => undefined);
            }}
          >
            查看本地日志目录
          </button>
          <button
            type="button"
            className="button"
            onClick={() => {
              void import("@tauri-apps/api/core")
                .then((m) => m.invoke("quit_app"))
                .catch(() => window.close());
            }}
          >
            退出
          </button>
        </div>
      </div>
    );
  }

  if (!connection) {
    return <div className="bootstrap-loading">正在启动本地服务…</div>;
  }

  return <App api={new ApiClient(connection)} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Bootstrap />
    </QueryClientProvider>
  </StrictMode>,
);
