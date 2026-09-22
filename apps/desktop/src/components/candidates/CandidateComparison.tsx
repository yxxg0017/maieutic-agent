/** CandidateComparison：并排对比，固定维度列，不用单一总分掩盖差异。 */
import { useState } from "react";

import type { Candidate } from "../../types/protocol";

const ROWS: { key: keyof Candidate | "scores"; label: string }[] = [
  { key: "text", label: "核心想法" },
  { key: "differentiator", label: "关键差异" },
  { key: "mechanism", label: "机制" },
  { key: "evidence_ids", label: "依据" },
  { key: "assumptions", label: "假设" },
  { key: "failure_modes", label: "失败模式" },
  { key: "verification", label: "最低成本验证" },
  { key: "scores", label: "各维度评分" },
];

const STATUS_LABEL: Record<string, string> = {
  generated: "待裁决",
  kept: "保留",
  combined: "组合",
  rejected: "淘汰",
};

function statusLabel(status: string | undefined): string {
  return STATUS_LABEL[status ?? "generated"] ?? status ?? "待裁决";
}

function renderCell(candidate: Candidate, key: (typeof ROWS)[number]["key"]) {
  if (key === "scores") {
    const entries = Object.entries(candidate.scores ?? {}).filter(([name]) => name !== "aggregate");
    if (entries.length === 0) return <span className="muted">未评分</span>;
    return (
      <ul className="score-list">
        {entries.map(([name, value]) => (
          <li key={name}>
            {name}: {Number(value).toFixed(2)}
          </li>
        ))}
      </ul>
    );
  }
  const value = candidate[key];
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="muted">无</span>;
    return (
      <ul>
        {value.map((item) => (
          <li key={String(item)}>{String(item)}</li>
        ))}
      </ul>
    );
  }
  return <span>{String(value ?? "") || <span className="muted">无</span>}</span>;
}

export function CandidateComparison(props: {
  candidates: Candidate[];
  onDecide: (candidateId: string, status: string, note?: string) => Promise<void>;
}) {
  const { candidates, onDecide } = props;
  const [notes, setNotes] = useState<Record<string, string>>({});

  if (candidates.length === 0) {
    return <p className="empty-note">暂无候选。深度模式会生成 2～5 个实质不同的候选后再比较。</p>;
  }

  return (
    <div className="candidate-comparison">
      <div className="candidate-grid" style={{ gridTemplateColumns: `8rem repeat(${candidates.length}, minmax(14rem, 1fr))` }}>
        <div className="grid-cell head" />
        {candidates.map((candidate) => (
          <div key={`head-${candidate.id}`} className="grid-cell head">
            <span className="status-badge" data-status={candidate.status}>
              {statusLabel(candidate.status)}
            </span>
          </div>
        ))}
        {ROWS.map((row) => (
          <div key={row.key} className="grid-row" style={{ display: "contents" }}>
            <div className="grid-cell label">{row.label}</div>
            {candidates.map((candidate) => (
              <div key={`${row.key}-${candidate.id}`} className="grid-cell">
                {renderCell(candidate, row.key)}
              </div>
            ))}
          </div>
        ))}
        <div className="grid-cell label">你的裁决</div>
        {candidates.map((candidate) => (
          <div key={`decide-${candidate.id}`} className="grid-cell">
            <div className="decision-buttons">
              {["kept", "combined", "rejected"].map((status) => (
                <button
                  key={status}
                  type="button"
                  className="button small"
                  aria-pressed={candidate.status === status}
                  onClick={() => void onDecide(candidate.id, status, notes[candidate.id] ?? "")}
                >
                  {STATUS_LABEL[status]}
                </button>
              ))}
            </div>
            <textarea
              className="candidate-note"
              rows={2}
              placeholder="备注（会随裁决保存）"
              value={notes[candidate.id] ?? candidate.user_note ?? ""}
              onChange={(event) =>
                setNotes((previous) => ({ ...previous, [candidate.id]: event.target.value }))
              }
            />
          </div>
        ))}
      </div>
    </div>
  );
}
