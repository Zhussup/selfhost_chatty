import type { FormEvent, KeyboardEvent } from "react";
import { useRef, useState } from "react";
import { usePane, usePaneId } from "./PaneContext";
import { useStore } from "../state";
import { modeById, parseSlash } from "../modes";
import ConfirmDialog from "./ConfirmDialog";
import ModePicker from "./ModePicker";
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
  const [error, setError] = useState("");
  // A slash command that needs confirming: the typed text stays in the box
  // until the user answers, so a cancel loses nothing.
  const [pending, setPending] = useState<{ modeId: string; content: string; warn: string } | null>(
    null
  );
  const taRef = useRef<HTMLTextAreaElement>(null);
  const turn = usePane((p) => p.turn, null);
  const model = usePane((p) => p.model, "");
  const think = usePane((p) => p.think, null);
  const useTools = usePane((p) => p.useTools, true);
  const mode = usePane((p) => p.mode, "assistant");
  const busy = usePane((p) => p.busy, false);
  const quote = usePane((p) => p.quote, null);

  const streaming = !!turn && !turn.done;
  const modes = useStore((st) => st.modes);
  const modeInfo = modeById(modes, mode);
  // A mode that pins tool calling owns the toggle — clicking it would lie.
  const toolsLocked = modeInfo ? modeInfo.tools !== "auto" : false;
  const pendingTitle = pending ? (modeById(modes, pending.modeId)?.title ?? "this mode") : "";

  const clear = () => {
    setText("");
    if (taRef.current) taRef.current.style.height = "auto";
  };

  const submit = () => {
    const value = text.trim();
    if (!value || busy || !model) return;
    setError("");

    const slash = parseSlash(value, useStore.getState().modes);
    if (slash?.kind === "unknown") {
      setError(`Unknown mode: /${slash.token}`);
      return; // keep the text so it can be corrected
    }
    if (slash?.kind === "mode") {
      const already = useStore.getState().panes[paneId]?.mode === slash.mode.id;
      if (slash.mode.warn && !already) {
        setPending({ modeId: slash.mode.id, content: slash.content, warn: slash.mode.warn });
        return; // nothing is sent or cleared until this is answered
      }
      useStore.getState().setMode(paneId, slash.mode.id);
      if (!slash.content) {
        clear(); // a bare "/fact" only switches persona
        return;
      }
      clear();
      useStore.getState().send(paneId, slash.content);
      return;
    }

    clear();
    useStore.getState().send(paneId, value);
  };

  /** Answer the slash-path confirmation: apply and send, or keep the text. */
  const resolve = (accept: boolean) => {
    const p = pending;
    setPending(null);
    if (!p) return;
    if (!accept) return; // the composer still holds what was typed
    useStore.getState().setMode(paneId, p.modeId);
    clear();
    if (p.content) useStore.getState().send(paneId, p.content);
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
        {quote && (
          <div className="composer-quote">
            <Icon name="quote" size={13} />
            <span className="composer-quote-text">{quote}</span>
            <button
              type="button"
              className="icon"
              title="Remove quote"
              onClick={() => {
                useStore.getState().clearQuote(paneId);
                taRef.current?.focus();
              }}
            >
              <Icon name="close" size={13} />
            </button>
          </div>
        )}
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
          <ModePicker />
          <button
            type="button"
            className={useTools ? "icon on" : "icon"}
            onClick={() => useStore.getState().toggleTools(paneId)}
            disabled={toolsLocked}
            title={
              toolsLocked
                ? `Tools are fixed by ${modeInfo?.title} mode`
                : "Toggle tool calling"
            }
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
      {error && <div className="composer-hint error">{error}</div>}
      {!empty && !error && (
        <div className="composer-hint">
          <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line
        </div>
      )}
      <ConfirmDialog
        open={!!pending}
        title={`Switch to ${pendingTitle}?`}
        body={pending?.warn ?? ""}
        confirmLabel="Switch"
        onConfirm={() => resolve(true)}
        onCancel={() => resolve(false)}
      />
    </form>
  );
}
