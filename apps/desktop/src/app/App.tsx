/** 主布局：会话列表 / 对话与学习检查 / 知识工作区。 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import { CandidateComparison } from "../components/candidates/CandidateComparison";
import { ChallengeList } from "../components/challenges/ChallengeCard";
import { Conversation } from "../components/conversation/Conversation";
import { InterruptForm } from "../components/conversation/InterruptForm";
import { PhaseIndicator } from "../components/conversation/PhaseIndicator";
import { TaskFrameCard } from "../components/frame/TaskFrameCard";
import { LearningCheckList } from "../components/learning/LearningCheck";
import { SessionList } from "../components/SessionList";
import { SettingsPanel } from "../components/SettingsPanel";
import { SourceList } from "../components/sources/SourceCard";
import type { ApiClient } from "../runtime/apiClient";
import { useKelRuntime } from "../runtime/assistantRuntime";
import { useSessionRuntime } from "../runtime/useSessionRuntime";
import { useUiStore } from "../stores/uiStore";

const EXAMPLES = [
  "巩固 Python：我会用生成器，但预测不了求值时机",
  "学习 Unity：想用一个小项目串起场景、组件与物理",
  "理解 LangGraph：想建立状态、中断与持久化的心智模型",
  "比较两种架构：需要找出真正的分歧和隐含成本",
  "头脑风暴：给这个产品想几个机制不同的方向",
];

const TABS = [
  { id: "frame", label: "目标与结论" },
  { id: "sources", label: "来源" },
  { id: "candidates", label: "候选对比" },
  { id: "boundaries", label: "边界与未知" },
] as const;

export function App(props: { api: ApiClient }) {
  const { api } = props;
  const queryClient = useQueryClient();
  const { sessionId, setSessionId, workspaceOpen, setWorkspaceOpen, workspaceTab, setWorkspaceTab, settingsOpen, setSettingsOpen } =
    useUiStore();
  const session = useSessionRuntime(api, sessionId);
  const { state } = session;

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId;
    const created = await api.createSession();
    await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    setSessionId(created.session_id);
    return created.session_id;
  }, [api, queryClient, sessionId, setSessionId]);

  const send = useCallback(
    async (text: string) => {
      const id = await ensureSession();
      if (id !== sessionId) {
        // 新会话刚建立，直接用 API 发送；SSE 订阅会在切换后补发历史事件。
        await api.sendMessage(id, text);
        return;
      }
      await session.send(text);
    },
    [api, ensureSession, session, sessionId],
  );

  const runtime = useKelRuntime({
    messages: state.messages,
    runStatus: state.runStatus,
    onNew: send,
    onCancel: session.cancel,
  });

  const exportSession = useMutation({
    mutationFn: () => api.exportSession(sessionId ?? ""),
  });

  const depth = useMemo<"fast" | "deep">(
    () => (state.candidates.length > 0 || state.phase === "clarify" ? "deep" : "fast"),
    [state.candidates.length, state.phase],
  );

  return (
    <div className="layout">
      <aside className="pane pane-sessions">
        <header className="pane-header">
          <h1>知识激发</h1>
          <button type="button" className="button small" onClick={() => setSettingsOpen(true)}>
            设置
          </button>
        </header>
        <SessionList api={api} activeSessionId={sessionId} onSelect={setSessionId} />
      </aside>

      <main className="pane pane-conversation">
        <Conversation
          runtime={runtime}
          header={
            <PhaseIndicator
              phase={state.phase}
              runStatus={state.runStatus}
              depth={depth}
              connected={state.connected || !sessionId}
              degradations={state.degradations}
            />
          }
          interrupt={<InterruptForm pending={state.pendingInterrupt} onSubmit={session.resume} />}
          footer={
            <div className="conversation-footer">
              <LearningCheckList checks={state.learningChecks} />
              {state.error ? (
                <p className="error-note" role="alert">
                  {state.error.code}：{state.error.message}
                </p>
              ) : null}
              <button
                type="button"
                className="button small"
                onClick={() => setWorkspaceOpen(!workspaceOpen)}
              >
                {workspaceOpen ? "收起知识工作区" : "展开知识工作区"}
              </button>
            </div>
          }
          emptyState={
            <section className="empty-state">
              <h2>说明你的目标，而不是只问一个题目</h2>
              <p>可以直接输入任何问题；以下只是提示，不是必须选项。</p>
              <ul>
                {EXAMPLES.map((example) => (
                  <li key={example}>{example}</li>
                ))}
              </ul>
            </section>
          }
        />
      </main>

      <aside
        className="pane pane-workspace"
        data-open={workspaceOpen}
        aria-label="知识工作区"
      >
        <header className="pane-header">
          <nav className="tabs">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className="tab"
                aria-selected={workspaceTab === tab.id}
                onClick={() => setWorkspaceTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </nav>
          <button
            type="button"
            className="button small"
            disabled={!sessionId || exportSession.isPending}
            onClick={() => exportSession.mutate()}
          >
            导出
          </button>
        </header>
        <div className="pane-body">
          {workspaceTab === "frame" ? (
            <TaskFrameCard
              topic={state.messages.find((m) => m.role === "user")?.content ?? ""}
              taskType={depth === "deep" ? "深度任务" : "快速任务"}
              depth={depth}
              phase={state.phase}
              claims={state.claims}
              nextSteps={state.nextSteps}
              onRestate={send}
            />
          ) : null}
          {workspaceTab === "sources" ? (
            <SourceList sources={state.sources} claims={state.claims} />
          ) : null}
          {workspaceTab === "candidates" ? (
            <CandidateComparison
              candidates={state.candidates}
              onDecide={session.decideCandidate}
            />
          ) : null}
          {workspaceTab === "boundaries" ? (
            <ChallengeList
              challenges={state.challenges}
              unknowns={state.unknowns}
              onDecide={session.decideChallenge}
            />
          ) : null}
          {exportSession.data ? (
            <p className="export-note">已导出 {exportSession.data.files.length} 个文件到本地导出目录。</p>
          ) : null}
        </div>
      </aside>

      {settingsOpen ? <SettingsPanel api={api} onClose={() => setSettingsOpen(false)} /> : null}
    </div>
  );
}
