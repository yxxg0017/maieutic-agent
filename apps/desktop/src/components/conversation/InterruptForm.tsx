/** interrupt 表单：澄清问题与学习检查。通过 /resume 提交，不作为普通消息发送。 */
import { useState } from "react";

import type { InterruptPayload } from "../../types/protocol";

export function InterruptForm(props: {
  pending: (InterruptPayload & { predicted_eig?: number }) | null;
  onSubmit: (body: { optionId?: string | null; freeText?: string }) => Promise<void>;
}) {
  const { pending, onSubmit } = props;
  const [optionId, setOptionId] = useState<string | null>(null);
  const [freeText, setFreeText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!pending) return null;
  const isQuestion = pending.kind === "question";
  const options = pending.options ?? [];

  const submit = async () => {
    setSubmitting(true);
    try {
      await onSubmit({ optionId, freeText });
      setOptionId(null);
      setFreeText("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      className="interrupt-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <p className="interrupt-kind">{isQuestion ? "需要你确认一件事" : "学习检查"}</p>
      <p className="interrupt-text">{pending.text}</p>
      {options.length > 0 ? (
        <fieldset className="interrupt-options">
          <legend>选择最接近的一项</legend>
          {options.map((option) => (
            <label key={option.id}>
              <input
                type="radio"
                name="interrupt-option"
                value={option.id}
                checked={optionId === option.id}
                onChange={() => setOptionId(option.id)}
              />
              {option.label}
            </label>
          ))}
        </fieldset>
      ) : null}
      {pending.free_text_allowed ? (
        <textarea
          className="interrupt-textarea"
          value={freeText}
          placeholder={isQuestion ? "补充说明（可选）" : "写下你的解释、预测或实现思路"}
          onChange={(event) => setFreeText(event.target.value)}
          rows={isQuestion ? 2 : 5}
        />
      ) : null}
      <div className="interrupt-actions">
        <button
          type="submit"
          className="button primary"
          disabled={submitting || (isQuestion && !optionId && !freeText.trim())}
        >
          提交
        </button>
        <button
          type="button"
          className="button"
          disabled={submitting}
          onClick={() => void onSubmit({ optionId: "uncertain", freeText: "" })}
        >
          我不确定，直接继续
        </button>
      </div>
    </form>
  );
}
