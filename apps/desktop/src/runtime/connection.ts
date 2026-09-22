/** 获取 sidecar 连接信息。正式包从 Tauri 命令获取；开发模式回退到环境变量。 */
import type { SidecarConnection } from "./apiClient";

type TauriInvoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

async function tauriInvoke(): Promise<TauriInvoke | null> {
  if (!("__TAURI_INTERNALS__" in window)) return null;
  const module = await import("@tauri-apps/api/core");
  return module.invoke as TauriInvoke;
}

export async function resolveConnection(): Promise<SidecarConnection> {
  const invoke = await tauriInvoke();
  if (invoke) {
    const info = await invoke<{ port: number; token: string }>("sidecar_connection");
    return { baseUrl: `http://127.0.0.1:${info.port}`, token: info.token };
  }
  const baseUrl = import.meta.env.VITE_SIDECAR_URL;
  const token = import.meta.env.VITE_SIDECAR_TOKEN;
  if (!baseUrl || !token) {
    throw new Error("sidecar_connection_unavailable");
  }
  return { baseUrl, token };
}

/** 外链只允许 https，并在打开前提示域名。 */
export async function openExternal(url: string): Promise<boolean> {
  if (!url.startsWith("https://")) return false;
  const host = new URL(url).host;
  if (!window.confirm(`将在浏览器打开外部域名：${host}\n是否继续？`)) return false;
  const invoke = await tauriInvoke();
  if (invoke) {
    await invoke("open_external", { url });
  } else {
    window.open(url, "_blank", "noopener,noreferrer");
  }
  return true;
}
