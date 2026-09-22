/** LearningCheck：展示检查任务与达标信号；不把正确率等同于掌握。 */
import type { LearningCheck as LearningCheckModel } from "../../types/protocol";

const KIND_LABEL: Record<string, string> = {
  explain: "解释",
  predict: "预测",
  exercise: "最小练习",
  implement: "实现任务",
};

export function LearningCheckCard(props: { check: LearningCheckModel }) {
  const { check } = props;
  return (
    <article className="card learning-card" data-status={check.status}>
      <header>
        <span className="status-badge">{KIND_LABEL[check.kind] ?? check.kind}</span>
        <span>{check.status === "answered" ? "已作答" : check.status === "skipped" ? "已跳过" : "待作答"}</span>
      </header>
      <p className="learning-prompt">{check.prompt}</p>
      {(check.expected_signals ?? []).length > 0 ? (
        <section>
          <h5>达标信号</h5>
          <ul>
            {(check.expected_signals ?? []).map((signal) => (
              <li key={signal}>{signal}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {check.user_answer ? (
        <section>
          <h5>你的回答</h5>
          <p className="learning-answer">{check.user_answer}</p>
        </section>
      ) : null}
      {check.feedback ? (
        <section>
          <h5>反馈</h5>
          <p>{check.feedback}</p>
        </section>
      ) : null}
    </article>
  );
}

export function LearningCheckList(props: { checks: LearningCheckModel[] }) {
  if (props.checks.length === 0) return null;
  return (
    <div className="card-list">
      {props.checks.map((check) => (
        <LearningCheckCard key={check.id} check={check} />
      ))}
    </div>
  );
}
