/**
 * assistant-ui 自定义 runtime adapter。
 * 组件只负责展示与交互；Agent 状态机仍在后端 LangGraph 中。
 */
import {
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { useMemo } from "react";

import type { ChatMessage, RunStatus } from "./eventReducer";

function convertMessage(message: ChatMessage): ThreadMessageLike {
  return {
    id: message.id,
    role: message.role,
    content: [{ type: "text", text: message.content }],
    status:
      message.role === "assistant" && message.streaming
        ? { type: "running" }
        : { type: "complete", reason: "stop" },
  };
}

export function useKelRuntime(options: {
  messages: ChatMessage[];
  runStatus: RunStatus;
  onNew: (text: string) => Promise<void>;
  onCancel: () => Promise<void>;
}) {
  const { messages, runStatus, onNew, onCancel } = options;
  const isRunning = runStatus === "running";

  return useExternalStoreRuntime(
    useMemo(
      () => ({
        isRunning,
        messages,
        convertMessage,
        onNew: async (message: AppendMessage) => {
          const text = message.content
            .filter((part): part is { type: "text"; text: string } => part.type === "text")
            .map((part) => part.text)
            .join("\n");
          if (text.trim()) await onNew(text);
        },
        onCancel,
      }),
      [isRunning, messages, onNew, onCancel],
    ),
  );
}
