import type { FormEvent, KeyboardEvent } from "react";
import { useRef, useState } from "react";
import { usePane, usePaneId } from "./PaneContext";
import { useStore } from "../state";

export default function Composer() {
  const paneId = usePaneId();
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const turn = usePane((p) => p.turn, null);
  const model = usePane((p) => p.model, "");
  const think = usePane((p) => p.think, null);
  const useTools = usePane((p) => p.useTools, true);
  const busy = usePane((p) => p.busy, false);

  const streaming = !!turn && !turn.done;

  const submit = () => {
    const value = text.trim();
    if (!value || busy || !model) return;
    setText("");
    if (taRef.current) taRef.current.style.height = "auto";
    useStore.getState().send(paneId, value);
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
        />
        {streaming ? (
          <button type="button" className="send stop" onClick={() => useStore.getState().stop(paneId)}>
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
          onClick={() => useStore.getState().toggleTools(paneId)}
          title="Toggle tool calling"
        >
          🛠 tools {useTools ? "on" : "off"}
        </button>
        <button
          type="button"
          className={`pill ${think ? "on" : ""}`}
          onClick={() => useStore.getState().cycleThink(paneId)}
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
