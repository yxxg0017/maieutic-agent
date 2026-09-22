/** TaskFrameCard：目标、任务类型、深度与价值标准；修正目标会开启新 run。 */
import { useState } from "react";

import type { Claim } from "../../types/protocol";

export function TaskFrameCard(props: {
  topic: string;
  taskType: string;
  depth: "fast" | "deep";
  phase: string;
  claims: Claim[];
  nextSteps: string[];
  onRestate: (topic: string) => Promise<void>;
}) {
  const { topic, taskType, depth, phase, claims, nextSteps, onRestate } = props;
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);

  return (
    <section className="card frame-card">
      <header>
        <h4>任务目标</h4>
        <span className="status-badge">{depth === "deep" ? "深度" : "快速"}</span>
      </header>
      <p className="frame-topic">{topic || "尚未框定"}</p>
      <dl>
        <dt>任务类型</dt>
        <dd>{taskType}</dd>
        <dt>当前阶段</dt>
        <dd>{phase}</dd>
      </dl>
      {claims.length > 0 ? (
        <section>
          <h5>结论 Claim</h5>
          <ul className="claim-list">
            {claims.map((claim) => (
              <li key={claim.id} data-tier={claim.source_tier}>
                <span className="tier-badge" data-tier={claim.source_tier}>
                  {claim.source_tier === "primary" ? "有来源" : "未核验"}
                </span>
                {claim.text}
                {(claim.boundaries ?? []).length > 0 ? (
                  <ul>
                    {(claim.boundaries ?? []).map((boundary) => (
                      <li key={boundary.text} className="boundary">
                        边界（{boundary.status}）：{boundary.text}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {nextSteps.length > 0 ? (
        <section>
          <h5>下一步</h5>
          <ul>
            {nextSteps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {editing ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!draft.trim()) return;
            void onRestate(draft.trim());
            setDraft("");
            setEditing(false);
          }}
        >
          <textarea
            rows={3}
            value={draft}
            placeholder="更准确地描述你的目标；提交会开启新的一轮，不修改历史回放"
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit" className="button primary">
            按新目标重新开始
          </button>
        </form>
      ) : (
        <button type="button" className="button" onClick={() => setEditing(true)}>
          修正目标
        </button>
      )}
    </section>
  );
}
