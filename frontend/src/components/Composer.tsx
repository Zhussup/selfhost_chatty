import type { FormEvent, KeyboardEvent } from "react";
import { useRef, useState } from "react";
import { usePane, usePaneId } from "./PaneContext";
import { useStore } from "../state";
import Icon from "./Icon";

const SUGGESTIONS = [
  "Search the web for today's news",
  "Run some Python for me",
  "Do a quick calculation",
  "Remember a note for later",
];

/** `empty` only changes styling and shows the suggestion chips — the form is
 *  rendered at the same tree position in both states, so typed text and focus
 *  survive the empty→non-empty transition. */
export default function Composer({ empty = false }: { empty?: boolean }) {
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

  const prefill = (s: string) => {
    setText(s);
    requestAnimationFrame(() => {
      const el = taRef.current;
      if (!el) return;
      autoGrow(el);
      el.focus();
      el.setSelectionRange(s.length, s.length);
    });
  };

  return (
    <form className="composer" onSubmit={onSubmit}>
      {/* DOM index 0 in every state — never insert a sibling before this card */}
      <div className="composer-card">
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
        <div className="composer-bar">
          <button
            type="button"
            className={useTools ? "icon on" : "icon"}
            onClick={() => useStore.getState().toggleTools(paneId)}
            title="Toggle tool calling"
          >
            <Icon name="wrench" size={16} />
            <span className="hide-narrow">tools</span>
          </button>
          <button
            type="button"
            className={think ? "icon on" : "icon"}
            onClick={() => useStore.getState().cycleThink(paneId)}
            title="Reasoning level (cycles: off → low → medium → high)"
          >
            <Icon name="bulb" size={16} />
            <span className="hide-narrow">think{think ? `: ${think}` : ""}</span>
          </button>
          <div className="grow" />
          {turn?.usage && turn.done && (
            <span className="usage-hint">
              {turn.usage.prompt} in + {turn.usage.completion} out
            </span>
          )}
          {streaming ? (
            <button
              type="button"
              className="send stop"
              title="Stop"
              onClick={() => useStore.getState().stop(paneId)}
            >
              <Icon name="stop" size={16} />
            </button>
          ) : (
            <button
              type="submit"
              className="send"
              title="Send"
              disabled={busy || !text.trim() || !model}
            >
              <Icon name="send" size={18} />
            </button>
          )}
        </div>
      </div>
      {/* DOM-last, shown above the card via `order: -1` in CSS */}
      {empty && (
        <div className="suggestions">
          {SUGGESTIONS.map((s) => (
            <button type="button" key={s} className="suggestion" onClick={() => prefill(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      {!empty && (
        <div className="composer-hint">
          <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line
        </div>
      )}
    </form>
  );
}
