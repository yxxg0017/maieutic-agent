/** 阶段指示：只显示当前阶段与用户可理解的进度，不展示隐藏思维链。 */
import type { RunStatus } from "../../runtime/eventReducer";

const PHASE_LABELS: Record<string, string> = {
  idle: "等待输入",
  task_frame: "框定任务",
  clarify: "澄清关键信息",
  source: "读取资料",
  diverge: "生成候选",
  challenge: "寻找反例与边界",
  synthesize: "综合结论",
  learn_check: "学习检查",
  fast_answer: "直接作答",
  finalize: "整理输出",
  completed: "已完成",
};

const DEEP_ORDER = [
  "task_frame",
  "clarify",
  "source",
  "diverge",
  "challenge",
  "synthesize",
  "learn_check",
  "completed",
];

export function PhaseIndicator(props: {
  phase: string;
  runStatus: RunStatus;
  depth: "fast" | "deep";
  connected: boolean;
  degradations: string[];
}) {
  const { phase, runStatus, depth, connected, degradations } = props;
  const index = DEEP_ORDER.indexOf(phase);
  return (
    <div className="phase-indicator">
      <span className="phase-current" data-status={runStatus}>
        {PHASE_LABELS[phase] ?? phase}
      </span>
      {depth === "deep" && index >= 0 ? (
        <span className="phase-progress" aria-label="深度流程进度">
          {index + 1} / {DEEP_ORDER.length}
        </span>
      ) : null}
      <span className="phase-depth">{depth === "deep" ? "深度模式" : "快速模式"}</span>
      {!connected ? <span className="phase-warning">事件连接已断开，正在重连</span> : null}
      {degradations.length > 0 ? (
        <details className="phase-degradations">
          <summary>{degradations.length} 项降级</summary>
          <ul>
            {degradations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
