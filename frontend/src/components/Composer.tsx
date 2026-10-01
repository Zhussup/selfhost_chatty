import type { FormEvent, KeyboardEvent } from "react";
import { useRef, useState } from "react";
import { useStore } from "../state";

export default function Composer() {
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const turn = useStore((st) => st.turn);
  const model = useStore((st) => st.model);
  const think = useStore((st) => st.think);
  const useTools = useStore((st) => st.useTools);
  const busy = useStore((st) => st.busy);

  const streaming = !!turn && !turn.done;

  const submit = () => {
    const value = text.trim();
    if (!value || busy || !model) return;
    setText("");
    if (taRef.current) taRef.current.style.height = "auto";
    useStore.getState().send(value);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const autoGrow = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  };

  return (
    <form className="composer" onSubmit={onSubmit}>
      <div className="composer-row main">
        <textarea
          ref={taRef}
          placeholder={model ? `Message ${model}…` : "Pick a model first…"}
          rows={1}
          value={text}
          disabled={busy && !streaming}
          onKeyDown={onKeyDown}
          onInput={(e) => autoGrow(e.target as HTMLTextAreaElement)}
          onChange={(e) => setText(e.target.value)}
          autoFocus
        />
        {streaming ? (
          <button type="button" className="send stop" onClick={() => useStore.getState().stop()}>
            Stop
          </button>
        ) : (
          <button type="submit" className="send" disabled={busy || !text.trim() || !model}>
            Send
          </button>
        )}
      </div>
      <div className="composer-row controls">
        <button
          type="button"
          className={`pill ${useTools ? "on" : ""}`}
          onClick={() => useStore.getState().toggleTools()}
          title="Toggle tool calling"
        >
          🛠 tools {useTools ? "on" : "off"}
        </button>
        <button
          type="button"
          className={`pill ${think ? "on" : ""}`}
          onClick={() => useStore.getState().cycleThink()}
          title="Reasoning level (cycles: off → low → medium → high)"
        >
          💭 think: {think ?? "off"}
        </button>
        <div className="grow" />
        {turn?.usage && turn.done && (
          <span className="usage-hint">
            {turn.usage.prompt} in + {turn.usage.completion} out tokens
          </span>
        )}
      </div>
    </form>
  );
}