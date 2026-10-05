import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Message from "./Message";
import Markdown from "./Markdown";
import ThinkingBlock from "./ThinkingBlock";
import ToolChip, { type ChipData } from "./ToolChip";
import Composer from "./Composer";
import ModelPicker from "./ModelPicker";
import MsgActions from "./MsgActions";
import ExportMenu from "./ExportMenu";
import Icon from "./Icon";
import { entriesFromHistory, entriesFromTurn } from "../export";
import { useTypewriter } from "./useTypewriter";
import { PaneProvider, usePane, usePaneId } from "./PaneContext";
import { useStore } from "../state";
import { MAX_QUOTE_CHARS } from "../panes";
import type { ChatTurn, MessageRow } from "../types";

const EMPTY_HISTORY: MessageRow[] = [];

/** Focus a pane's composer. Called from the keyboard/split paths, never on click. */
export function focusComposer(paneId: string): void {
  requestAnimationFrame(() => {
    document.querySelector<HTMLTextAreaElement>(`[data-pane="${paneId}"] textarea`)?.focus();
  });
}

function friendlyError(raw: string): string {
  if (raw.includes("rate_limited")) {
    return "Too many turns running (max 2) — stop another pane and retry.";
  }
  return raw;
}

export default function Pane({ paneId }: { paneId: string }) {
  const exists = useStore((st) => !!st.panes[paneId]);
  const focused = useStore((st) => st.focusedPaneId === paneId);

  // Focus the composer when this pane becomes focused, but only when nothing
  // else holds focus — so splitting never yanks the caret out of another pane.
  useEffect(() => {
    const active = document.activeElement;
    if (focused && (active === null || active === document.body)) focusComposer(paneId);
  }, [focused, paneId]);

  // a closed pane can still render one frame before its parent drops it
  if (!exists) return null;
  return (
    <PaneProvider paneId={paneId}>
      <section
        className={focused ? "pane focused" : "pane"}
        data-pane={paneId}
        onPointerDownCapture={() => useStore.getState().focusPane(paneId)}
      >
        <PaneHeader paneId={paneId} />
        <PaneBody />
      </section>
    </PaneProvider>
  );
}

/**
 * Module scope on purpose: defining this inside `Pane` would make a new
 * component type every render and remount the subtree (losing composer text).
 *
 * The child order is fixed — MessageList then the composer's wrapper — so the
 * empty→non-empty transition only flips a class on `.pane-body` and never
 * remounts `<Composer>`.
 */
function PaneBody() {
  const sessionId = usePane((p) => p.sessionId, null);
  const turn = usePane((p) => p.turn, null);
  const historyLen = usePane((p) => p.history.length, 0);
  const empty = sessionId === null && !turn && historyLen === 0;

  return (
    <div className={empty ? "pane-body empty" : "pane-body"}>
      <MessageList />
      <div className="composer-wrap">
        <Composer empty={empty} />
      </div>
    </div>
  );
}

function PaneHeader({ paneId }: { paneId: string }) {
  const sessionId = usePane((p) => p.sessionId, null);
  const streaming = usePane((p) => !!p.turn && !p.turn.done, false);
  const history = usePane((p) => p.history, EMPTY_HISTORY);
  const turn = usePane((p) => p.turn, null);
  const sessions = useStore((st) => st.sessions);
  const title = sessions.find((s) => s.id === sessionId)?.title ?? "New chat";
  // whole dialog — including the exchange still streaming, if any
  const exportEntries = [
    ...entriesFromHistory(history),
    ...(turn ? entriesFromTurn(turn) : []),
  ];

  const split = (dir: "row" | "col") => {
    useStore.getState().splitPane(paneId, dir);
    focusComposer(useStore.getState().focusedPaneId);
  };

  return (
    <div className="pane-head">
      {streaming && <span className="dot pulse" />}
      <span className="pane-title">{title}</span>
      <ModelPicker />
      <ExportMenu title={title} entries={exportEntries} />
      <button className="icon" title="Split right — Ctrl+Shift+E" onClick={() => split("row")}>
        <Icon name="splitV" />
      </button>
      <button className="icon" title="Split down — Ctrl+Shift+O" onClick={() => split("col")}>
        <Icon name="splitH" />
      </button>
      <button
        className="icon hide-narrow"
        title="Close pane — Ctrl+Shift+W"
        onClick={() => {
          useStore.getState().closePane(paneId);
          focusComposer(useStore.getState().focusedPaneId);
        }}
      >
        <Icon name="close" />
      </button>
    </div>
  );
}

function MessageList() {
  const paneId = usePaneId();
  const sessionId = usePane((p) => p.sessionId, null);
  const turn = usePane((p) => p.turn, null);
  const history = usePane((p) => p.history, EMPTY_HISTORY);
  const busy = usePane((p) => p.busy, false);
  const sessionTitle = useStore((st) => st.sessions.find((s) => s.id === sessionId)?.title);
  // Smooths the streamed answer; owned here (not in StreamingTurn) so the
  // scroll effect below can track the displayed length as it grows.
  const displayText = useTypewriter(turn?.text ?? "", !!turn && !turn.done);
  const stick = useRef(true);
  const listRef = useRef<HTMLDivElement>(null);
  // The reply affordance over a text selection. Local state on purpose: it
  // changes on every pointerup and no other pane should re-render for it.
  const [pill, setPill] = useState<{ text: string; x: number; y: number } | null>(null);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const hide = () => setPill(null);
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      hide(); // a selection anchored in viewport coords does not survive a scroll
    };
    const onPointerUp = (e: PointerEvent) => {
      if (e.button !== 0) return hide();
      const target = e.target as Element | null;
      if (!target || target.closest("button, a")) return hide();
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) return hide();
      const text = sel.toString().trim();
      if (text.length < 2) return hide();
      const node = sel.focusNode;
      const host = node && (node.nodeType === 1 ? (node as Element) : node.parentElement);
      if (!host || !el.contains(host) || !host.closest(".msg.assistant")) return hide();
      const capped =
        text.length > MAX_QUOTE_CHARS ? text.slice(0, MAX_QUOTE_CHARS).trimEnd() + "…" : text;
      // the last line of the selection, in viewport coords — the pill is portaled
      // to <body>, because `.pane` has container-type and would capture position:fixed
      const range = sel.getRangeAt(0);
      const rects = range.getClientRects();
      const rect = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
      if (!rect || (!rect.width && !rect.height)) return hide();
      setPill({
        text: capped,
        x: Math.min(Math.max(rect.left, 8), window.innerWidth - 252),
        y: rect.top < 60 ? rect.bottom + 8 : rect.top - 42,
      });
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") hide();
    };
    el.addEventListener("scroll", onScroll);
    el.addEventListener("pointerup", onPointerUp);
    window.addEventListener("resize", hide);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("resize", hide);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (stick.current && el) {
      // scrollTop, not scrollIntoView — the latter can scroll the outer pane tree
      el.scrollTop = el.scrollHeight;
    }
  }, [
    history.length,
    history[history.length - 1]?.content,
    displayText,
    turn?.think_text,
    turn?.tools.length,
    turn?.done,
  ]);

  const lastId = history[history.length - 1]?.id;

  return (
    <>
      <div className="msg-list" ref={listRef}>
        {sessionId === null && !turn && <Welcome />}
        {history.map((m) => {
          if (m.role === "assistant" && m.tool_calls && m.tool_calls.length && !m.content && !m.thinking) {
            // assistant rows that exist only to carry tool calls render through the tool rows
            return null;
          }
          // Only the newest answer can be regenerated — an older one would rerun
          // the tail exchange instead, which is not what the button promises.
          const canRetry = m.role === "assistant" && m.id === lastId && !busy && !turn;
          // Editing while a turn is in flight would race the stream's finalize.
          const canEdit = m.role === "user" && !busy && !turn;
          return (
            <div key={m.id}>
              <Message
                msg={m}
                sessionTitle={sessionTitle}
                onRetry={canRetry ? () => useStore.getState().retry(paneId) : undefined}
                onEdit={
                  canEdit
                    ? (text) => useStore.getState().editMessage(paneId, m.id, text)
                    : undefined
                }
              />
            </div>
          );
        })}
        {turn && showUserBubble(turn) && (
          <div className="msg user">
            <div className="bubble">
              {turn.quote ? <div className="bubble-quote">{turn.quote}</div> : null}
              {turn.user_text}
            </div>
          </div>
        )}
        {turn && <StreamingTurn turn={turn} text={displayText} />}
      </div>
      {pill &&
        createPortal(
          <button
            type="button"
            className="quote-pop"
            style={{ left: pill.x, top: pill.y }}
            // keeps the browser from collapsing the selection on mousedown, which
            // would drop the pill before the click lands
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              useStore.getState().setQuote(paneId, pill.text);
              focusComposer(paneId);
              window.getSelection()?.removeAllRanges();
              setPill(null);
            }}
          >
            <Icon name="quote" size={14} />
            <span className="quote-pop-text">{pill.text}</span>
            <span className="quote-pop-label">Reply</span>
          </button>,
          document.body
        )}
    </>
  );
}

/** The prompt is shown right away — but not when the turn never reached the
 *  server (e.g. 409 rate_limited), where nothing was persisted to show. */
function showUserBubble(turn: ChatTurn): boolean {
  return !!turn.user_text && (turn.session_id !== "" || !turn.error);
}

function StreamingTurn({ turn, text }: { turn: ChatTurn; text: string }) {
  const paneId = usePaneId();
  const busy = usePane((p) => p.busy, false);
  // Uses the *displayed* text, so the placeholder holds until the typewriter
  // has revealed its first characters instead of blinking empty.
  const waiting = !turn.done && !turn.error && !text && !turn.think_text && turn.tools.length === 0;
  return (
    <div className="msg assistant streaming">
      <div className="msg-avatar">
        <Icon name="sparkle" size={15} />
      </div>
      <div className="msg-main">
        {waiting && (
          <div className="waiting">
            <span className="ldot" />
            <span className="ldot" />
            <span className="ldot" />
          </div>
        )}
        <ThinkingBlock text={turn.think_text} active={!turn.done} />
        {turn.tools.map((t) => {
          const chip: ChipData = {
            id: t.id,
            name: t.name,
            arguments: t.arguments,
            ok: t.ok,
            ms: t.ms,
            result: t.result,
          };
          return <ToolChip key={t.id} chip={chip} />;
        })}
        <Markdown text={text} />
        {turn.error && <div className="error-note">{friendlyError(turn.error)}</div>}
        {turn.usage && (
          <div className="stamp">
            {turn.usage.prompt} in + {turn.usage.completion} out tokens{turn.done ? "" : " so far"}
          </div>
        )}
        {turn.done && !busy && (
          <MsgActions copyText={turn.text} onRetry={() => useStore.getState().retry(paneId)} />
        )}
      </div>
    </div>
  );
}

function Welcome() {
  return (
    <div className="welcome">
      <div className="welcome-mark">
        <Icon name="sparkle" size={26} />
      </div>
      <h1>How can I help you today?</h1>
      <p>
        Self-hosted chat on Ollama Cloud. Tools available: web search, page reading, exact
        math, python, long-term memory.
      </p>
    </div>
  );
}
