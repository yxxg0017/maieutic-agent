/** SourceCard：明显区分 primary / secondary / model_only。 */
import { openExternal } from "../../runtime/connection";
import type { Claim, EvidenceItem } from "../../types/protocol";

const TIER_LABEL: Record<string, string> = {
  primary: "一手来源",
  secondary: "二手总结",
  model_only: "模型已有知识，未核验",
};

export function SourceCard(props: { source: EvidenceItem; claims: Claim[] }) {
  const { source, claims } = props;
  const usedBy = claims.filter((claim) =>
    (claim.evidence_links ?? []).some((link) => link.evidence_id === source.id),
  );
  const isUrl = source.locator.startsWith("https://");

  return (
    <article className="card source-card" data-tier={source.source_tier}>
      <header>
        <span className="tier-badge" data-tier={source.source_tier}>
          {TIER_LABEL[source.source_tier] ?? source.source_tier}
        </span>
        <h4>{source.title || source.locator}</h4>
      </header>
      <dl>
        <dt>定位</dt>
        <dd className="locator">{source.locator}</dd>
        {source.version ? (
          <>
            <dt>版本</dt>
            <dd>{source.version}</dd>
          </>
        ) : null}
        <dt>类型</dt>
        <dd>{source.kind}</dd>
      </dl>
      {source.context ? <p className="snippet">{source.context}</p> : null}
      <footer>
        {isUrl ? (
          <button type="button" className="button" onClick={() => void openExternal(source.locator)}>
            打开来源
          </button>
        ) : null}
        <span className="used-by">
          {usedBy.length > 0 ? `被 ${usedBy.length} 条 Claim 使用` : "尚未被任何 Claim 使用"}
        </span>
      </footer>
    </article>
  );
}

export function SourceList(props: { sources: EvidenceItem[]; claims: Claim[] }) {
  if (props.sources.length === 0) {
    return (
      <p className="empty-note">
        暂无可定位来源。当前内容为模型已有知识，未核验；导入资料可提升可追溯性。
      </p>
    );
  }
  return (
    <div className="card-list">
      {props.sources.map((source) => (
        <SourceCard key={source.id} source={source} claims={props.claims} />
      ))}
    </div>
  );
}
