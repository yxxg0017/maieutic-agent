/** 对话区：assistant-ui 原语 + 安全 Markdown 渲染（不允许任意 HTML）。 */
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
} from "@assistant-ui/react";
import Markdown from "react-markdown";
import type { ReactNode } from "react";

function MarkdownText() {
  return (
    <MessagePrimitive.Parts
      components={{
        Text: ({ text }: { text: string }) => (
          // react-markdown 默认不渲染原始 HTML：模型输出按不可信内容处理
          <div className="markdown">
            <Markdown>{text}</Markdown>
          </div>
        ),
      }}
    />
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message message-user">
      <MarkdownText />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="message message-assistant">
      <MarkdownText />
    </MessagePrimitive.Root>
  );
}

export function Conversation(props: {
  runtime: ReturnType<typeof import("../../runtime/assistantRuntime").useKelRuntime>;
  header: ReactNode;
  interrupt: ReactNode;
  footer: ReactNode;
  emptyState: ReactNode;
}) {
  return (
    <AssistantRuntimeProvider runtime={props.runtime}>
      <ThreadPrimitive.Root className="thread">
        {props.header}
        <ThreadPrimitive.Viewport className="thread-viewport">
          <ThreadPrimitive.Empty>{props.emptyState}</ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages
            components={{ UserMessage, AssistantMessage }}
          />
          {props.interrupt}
        </ThreadPrimitive.Viewport>
        {props.footer}
        <ComposerPrimitive.Root className="composer">
          <ComposerPrimitive.Input
            className="composer-input"
            placeholder="描述你的目标、卡点或要比较的方案"
            autoFocus
          />
          <div className="composer-actions">
            <ThreadPrimitive.If running={false}>
              <ComposerPrimitive.Send className="button primary">发送</ComposerPrimitive.Send>
            </ThreadPrimitive.If>
            <ThreadPrimitive.If running>
              <ComposerPrimitive.Cancel className="button">停止</ComposerPrimitive.Cancel>
            </ThreadPrimitive.If>
          </div>
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
