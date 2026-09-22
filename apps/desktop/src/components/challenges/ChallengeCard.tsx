/** ChallengeCard：模型提议的边界与用户裁决分别标识。 */
import type { Challenge } from "../../types/protocol";

const DECISIONS: { status: string; label: string }[] = [
  { status: "holds", label: "成立" },
  { status: "does_not_hold", label: "不成立" },
  { status: "conditional", label: "仅在某条件成立" },
  { status: "not_encountered", label: "没遇到过" },
  { status: "unknown", label: "无法判断" },
];

const STATUS_LABEL: Record<string, string> = {
  untested: "模型提议，未裁决",
  ...Object.fromEntries(DECISIONS.map((d) => [d.status, `用户裁决：${d.label}`])),
};

function statusLabel(status: string | undefined): string {
  return STATUS_LABEL[status ?? "untested"] ?? status ?? "未裁决";
}

export function ChallengeCard(props: {
  challenge: Challenge;
  onDecide: (challengeId: string, status: string) => Promise<void>;
}) {
  const { challenge, onDecide } = props;
  return (
    <article className="card challenge-card" data-status={challenge.status}>
      <header>
        <span className="status-badge" data-status={challenge.status}>
          {statusLabel(challenge.status)}
        </span>
        <span className="source-badge">
          {challenge.source === "model_generated_probe" ? "模型提议" : "用户提供"}
        </span>
      </header>
      <p>{challenge.text}</p>
      <footer className="decision-buttons">
        {DECISIONS.map((decision) => (
          <button
            key={decision.status}
            type="button"
            className="button small"
            aria-pressed={challenge.status === decision.status}
            onClick={() => void onDecide(challenge.id, decision.status)}
          >
            {decision.label}
          </button>
        ))}
      </footer>
    </article>
  );
}

export function ChallengeList(props: {
  challenges: Challenge[];
  unknowns: string[];
  onDecide: (challengeId: string, status: string) => Promise<void>;
}) {
  return (
    <div className="card-list">
      {props.challenges.length === 0 ? (
        <p className="empty-note">暂无边界探针。</p>
      ) : (
        props.challenges.map((challenge) => (
          <ChallengeCard key={challenge.id} challenge={challenge} onDecide={props.onDecide} />
        ))
      )}
      {props.unknowns.length > 0 ? (
        <section className="card unknowns-card">
          <h4>未知项</h4>
          <ul>
            {props.unknowns.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
