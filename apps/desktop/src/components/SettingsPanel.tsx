/** 设置：模型服务与隐私提示。前端只能查询"是否已配置"，不能读回明文密钥。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { ApiClient } from "../runtime/apiClient";

export function SettingsPanel(props: { api: ApiClient; onClose: () => void }) {
  const { api, onClose } = props;
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() });
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");

  const save = useMutation({
    mutationFn: () => api.saveApiKey(apiKey, baseUrl || undefined, model || undefined),
    onSuccess: () => {
      setApiKey("");
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  return (
    <aside className="settings-panel" aria-label="设置">
      <header>
        <h3>设置</h3>
        <button type="button" className="button small" onClick={onClose}>
          关闭
        </button>
      </header>
      <p className="privacy-note">
        密钥保存在系统钥匙串，不写入数据库、日志或导出文件。
        {settings.data?.offline
          ? "当前为离线模式：资料不会离开本机。"
          : `启用模型服务后，你的问题与被引用的资料片段会发送到 ${settings.data?.base_url ?? "所选服务"}。`}
      </p>
      <dl>
        <dt>模型服务</dt>
        <dd>{settings.data?.model_configured ? "已配置" : "未配置"}</dd>
        <dt>本地数据目录</dt>
        <dd className="locator">{settings.data?.data_dir ?? "未知"}</dd>
      </dl>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (apiKey.trim().length >= 8) save.mutate();
        }}
      >
        <label>
          API Key
          <input
            type="password"
            value={apiKey}
            autoComplete="off"
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="仅写入钥匙串"
          />
        </label>
        <label>
          Base URL
          <input
            type="url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder={settings.data?.base_url ?? "https://api.openai.com/v1"}
          />
        </label>
        <label>
          模型
          <input
            type="text"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            placeholder={settings.data?.model ?? "gpt-4o-mini"}
          />
        </label>
        <button type="submit" className="button primary" disabled={save.isPending}>
          保存
        </button>
        {save.isError ? <p className="error-note">保存失败，请检查输入</p> : null}
      </form>
    </aside>
  );
}
